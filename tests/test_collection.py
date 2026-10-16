import asyncio
import base64
import gzip
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest
from app.collection import Collector, CollectionStore, daily_bars
from app.experiments.storage import DriveCredentials, DriveStorage

XML = b'<protocol><chartdata><item data="20261015|100|110|90|105|10"/></chartdata></protocol>'
RSS = b'<rss><channel><item><title>Test news</title><link>https://example.test/article</link></item></channel></rss>'
ENV = {'INVESTPILOT_COLLECTION_ENABLED':'true', 'INVESTPILOT_COLLECTION_SYMBOLS':'005930',
       'NEWS_RSS_URLS':'https://example.test/feed?secret=private-sentinel'}


@pytest.fixture
def store(tmp_path):
    return CollectionStore(tmp_path/'collection.db', database_url='')


def test_disabled_does_not_create_database_or_send_requests(tmp_path, monkeypatch):
    monkeypatch.setenv('INVESTPILOT_DATA_DIR',str(tmp_path))
    collector = Collector(env={})
    asyncio.run(collector.tick())
    assert collector.status()['enabled'] is False and not list(tmp_path.iterdir())


def test_restart_deduplicates_and_job_lease_is_atomic(store):
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(x is not None for x in pool.map(lambda _:store.claim('prices:005930'), range(8))) == 1
    assert store.save('prices', {'rows':[1]})
    again = CollectionStore(store.storage.path, database_url='')
    assert not again.save('prices', {'rows':[1]}) and again.claim('prices:005930') is None
    assert again.status()['pending'] == 1


def test_scheduled_collection_and_sanitized_errors(store):
    now = [100.0]
    store.clock = lambda: now[0]
    calls = []
    def handler(request):
        calls.append(str(request.url))
        if request.url.host == 'fchart.stock.naver.com':
            return httpx.Response(200, content=XML)
        return httpx.Response(200, content=RSS)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            collector = Collector(env=ENV, store=store, client=client)
            await collector.tick()
            assert store.status()['pending'] == 2
            await collector.tick()
            assert len(calls) == 2
            now[0] += 301
            await collector.tick()
            assert len(calls) == 3 and store.status()['pending'] == 2
    asyncio.run(run())
    rows = store.pending()
    for row in rows:
        raw = gzip.decompress(base64.b64decode(row['payload'])).decode()
        assert 'private-sentinel' not in raw
    assert 'private-sentinel' not in json.dumps(store.status())


def test_failure_backoff_restart_and_recovery(store):
    now = [100.0]
    store.clock = lambda: now[0]
    lease = store.claim('news:1')
    store.finish('news:1', lease, 300, False)
    assert store.claim('news:1') is None
    assert store.status()['jobs'][0]['failures'] == 1
    now[0] += 60
    lease = store.claim('news:1')
    store.finish('news:1', 'obsolete-lease', 300, True)
    assert store.status()['jobs'][0]['failures'] == 1
    store.finish('news:1', lease, 300, True)
    assert store.status()['jobs'][0]['failures'] == 0


def test_spool_budget_does_not_discard_pending(tmp_path):
    store = CollectionStore(tmp_path/'small.db', database_url='', budget=200)
    store.save('prices', {'rows':[1]})
    with pytest.raises(ValueError, match='spool full'):
        store.save('prices', {'rows':list(range(1000))})
    assert store.status()['pending'] == 1


def test_completed_bars_and_invalid_data():
    body = XML.replace(b'20261015', b'20261016')
    with pytest.raises(ValueError, match='history'):
        daily_bars(body, datetime(2026,10,16,5,0,tzinfo=timezone.utc))
    assert daily_bars(body, datetime(2026,10,16,7,0,tzinfo=timezone.utc))[0]['close'] == 105
    with pytest.raises(ValueError, match='OHLC'):
        daily_bars(XML.replace(b'|110|',b'|95|'))
    with pytest.raises(ValueError, match='Duplicate'):
        daily_bars(XML.replace(b'</chartdata>', b'<item data="20261015|100|110|90|105|10"/></chartdata>'))


def test_bad_source_and_bounded_response_record_failure(store):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200, content=b'x'*2_000_001))) as client:
            collector = Collector(env=ENV, store=store, client=client)
            await collector.tick()
    asyncio.run(run())
    assert store.status()['pending'] == 0
    assert all(j['error']=='collection_or_upload_failed' for j in store.status()['jobs'])


def test_upload_ack_and_retry_preserve_data(store):
    store.save('prices', {'rows':[1]})
    attempts = []
    class FakeStorage:
        client = type('Client', (), {'close':lambda self:None})()
        def upload(self, path, category, artifact_id=None):
            attempts.append(artifact_id)
            assert json.loads(gzip.decompress(Path(path).read_bytes())) == {'rows':[1]}
            if len(attempts) == 1:
                raise RuntimeError('private-sentinel')
            return {'id':'private-drive-id'}
    collector = Collector(env={**ENV,'INVESTPILOT_COLLECTION_DRIVE_ENABLED':'true'}, store=store, drive_factory=FakeStorage)
    collector.upload()
    assert store.status()['pending'] == 1
    store.clock = lambda: 10**12
    collector.upload()
    assert store.status()['pending'] == 0 and attempts[0] == attempts[1]
    assert 'private-drive-id' not in json.dumps(store.status())


def test_drive_idempotency_after_unacknowledged_upload(tmp_path):
    calls = []
    def handler(request):
        calls.append(request.method)
        return httpx.Response(200, json={'files':[{'id':'existing'}]})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        storage = DriveStorage(client)
        storage.settings['folders']['prices']='test-folder'
        # No local file needed if Drive already acknowledges the content digest.
        assert storage.upload(tmp_path/'missing.jsonl.gz','prices',artifact_id='a'*64)['id']=='existing'
    assert calls == ['GET']


def test_refresh_credentials_cached_and_missing_credentials_fail_closed():
    calls = []
    def handler(request):
        calls.append(request)
        assert request.url == 'https://oauth2.googleapis.com/token'
        return httpx.Response(200, json={'access_token':'temporary','expires_in':3600})
    env = {'GOOGLE_DRIVE_REFRESH_TOKEN':'test-refresh','GOOGLE_DRIVE_CLIENT_ID':'test-id','GOOGLE_DRIVE_CLIENT_SECRET':'test-secret'}
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        credentials = DriveCredentials(env=env,client=client)
        assert credentials.access_token() == credentials.access_token() == 'temporary'
        assert len(calls) == 1
    with pytest.raises(ValueError):
        DriveCredentials(env={}).access_token()


def test_postgres_collection_persists_and_locks(tmp_path):
    url = os.getenv('INVESTPILOT_TEST_POSTGRES_URL')
    if not url:
        pytest.skip('Disposable PostgreSQL required')
    assert urlsplit(url).hostname in ('localhost','127.0.0.1','::1')
    store = CollectionStore(tmp_path/'unused.db', database_url=url)
    with store.storage.db() as db:
        db.execute('DELETE FROM collection_jobs')
        db.execute('DELETE FROM collection_artifacts')
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(x is not None for x in pool.map(lambda _:store.claim('prices:test'), range(8))) == 1
    assert store.save('news', {'rows':[1]})
    again = CollectionStore(tmp_path/'other.db', database_url=url)
    assert again.status()['pending'] == 1 and not again.save('news', {'rows':[1]})
    assert not (tmp_path/'unused.db').exists()


def test_render_cannot_enable_ephemeral_collection():
    with pytest.raises(ValueError, match='persistent'):
        Collector(env={**ENV,'RENDER':'true'})


def test_status_route_requires_owner(store, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app import main
    from app.auth import AuthStore, AuthSettings, install_auth
    monkeypatch.setattr(main,'collector',Collector(env=ENV,store=store))
    auth = AuthStore(Path(store.storage.path).parent/'auth.db',database_url='')
    auth.configure('admin','test-password-12345')
    auth.add_user('other','test-password-12345')
    app = FastAPI()
    app.add_api_route('/api/collection/status',main.collection_status)
    install_auth(app,auth,AuthSettings(enabled=True,secure=False,public_origin='http://testserver'),Path('app/static'))
    with TestClient(app) as client:
        assert client.get('/api/collection/status').status_code == 401
        for user, status in [('other',403),('admin',200)]:
            assert client.post('/api/auth/login',headers={'Origin':'http://testserver'},json={'username':user,'password':'test-password-12345'}).status_code == 200
            response = client.get('/api/collection/status')
            assert response.status_code == status
            assert 'private-sentinel' not in response.text



def test_naver_euc_kr_source_is_decoded():
    body = ('<?xml version="1.0" encoding="EUC-KR"?>'
            '<protocol><chartdata name="삼성전자"><item data="20261015|100|110|90|105|10"/></chartdata></protocol>').encode('euc-kr')
    assert daily_bars(body)[0]['close'] == 105


def test_web_start_failure_cancels_collector(monkeypatch):
    from types import SimpleNamespace
    from app import main
    events=[]
    async def research(snapshot):
        try:
            await asyncio.Event().wait()
        finally:
            events.append('research-stopped')
    async def collection_loop():
        try:
            await asyncio.Event().wait()
        finally:
            events.append('collector-stopped')
    async def start():
        await asyncio.sleep(0)
        raise RuntimeError('test-startup-failure')
    async def stop():
        events.append('brokers-stopped')
    monkeypatch.setattr(main,'ai_experiment',SimpleNamespace(loop=research))
    monkeypatch.setattr(main,'collector',SimpleNamespace(enabled=True,loop=collection_loop))
    monkeypatch.setattr(main,'broker_accounts',SimpleNamespace(start=start,stop=stop))
    monkeypatch.setattr(main,'account_runtime',SimpleNamespace(tasks={}))
    async def run():
        with pytest.raises(RuntimeError,match='test-startup-failure'):
            async with main.lifespan(main.app):
                pytest.fail('Failed startup must not serve')
    asyncio.run(run())
    assert set(events)=={'research-stopped','collector-stopped','brokers-stopped'}
