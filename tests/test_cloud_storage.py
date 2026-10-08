"""Real PostgreSQL integration tests. Run only against a disposable local DB."""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urlsplit
import pytest
from app.auth import AuthStore, LoginFailed, RateLimited
from app.engine import Engine
from app.experiments.ai_paper import Wallet, Snapshot, Decision
from app.experiments.cloud_results import publish
from app.experiments.comparison import snapshot
from app.storage import SCHEMAS, Database, postgres_sql


def test_bind_markers_preserve_literals():
    assert postgres_sql("SELECT '?' AS literal, ? AS parameter") == "SELECT '?' AS literal, %s AS parameter"


def test_public_database_requires_tls(monkeypatch, tmp_path):
    monkeypatch.setenv('INVESTPILOT_DATABASE_URL', 'postgresql://user:secret@public.example/db?sslmode=disable')
    with pytest.raises(ValueError, match='TLS'):
        Database(tmp_path/'local.db', 'auth')
    assert not (tmp_path/'local.db').exists()


@pytest.fixture
def cloud(monkeypatch):
    url = os.getenv('INVESTPILOT_TEST_POSTGRES_URL')
    if not url: pytest.skip('Disposable PostgreSQL not configured')
    if urlsplit(url).hostname not in ('localhost', '127.0.0.1', '::1'):
        pytest.fail('Integration tests must never run against a cloud production DB')
    import psycopg
    with psycopg.connect(url) as db:
        for schema in SCHEMAS.values():
            db.execute(f'DROP SCHEMA IF EXISTS {schema} CASCADE')
    monkeypatch.setenv('INVESTPILOT_DATABASE_URL', url)
    return url


def test_owner_sessions_and_rate_limits_persist(cloud, tmp_path):
    first = AuthStore(tmp_path/'first.db')
    first.configure('admin', 'test-owner-password-123')
    token = first.login('admin', 'test-owner-password-123', 'good', 3600)
    second = AuthStore(tmp_path/'different.db')
    assert second.authenticate(token) == 'admin'
    def attempt(_):
        try: second.login('admin', 'wrong', 'bad', 3600)
        except (LoginFailed, RateLimited) as exc: return type(exc)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(attempt, range(10)))
    assert results.count(LoginFailed) == 5
    assert results.count(RateLimited) == 5
    second.revoke(token)
    assert first.authenticate(token) is None
    assert not (tmp_path/'first.db').exists()


def test_concurrent_paper_orders_never_overspend(cloud, tmp_path):
    first = Engine(tmp_path/'one.db')
    second = Engine(tmp_path/'two.db')
    with first.db() as db: db.execute("UPDATE settings SET value='100000' WHERE key='cash'")
    first.quote('005930', 10000, 0)
    def order(pair):
        engine, key = pair
        try: return engine.order('005930', 'buy', 8, key)
        except ValueError: return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(order, [(first, 'one'), (second, 'two')]))
    assert sum(r is not None for r in results) == 1
    state = Engine(tmp_path/'restart.db').snapshot()
    assert state['cash'] == 20000 and state['positions'][0]['qty'] == 8
    # Retry the successful request; it must not spend twice.
    key = next(r['id'] for r in results if r)
    first.order('005930', 'buy', 8, key)
    assert second.snapshot()['cash'] == 20000
    second.quote('005930', 11000, 0)
    assert first.history('005930')[-1]['price'] == 11000
    first.market_tick('peer', 100, datetime.now(timezone.utc).isoformat())
    assert second.market_history('peer')[0]['price'] == 100


def test_ai_wallet_survives_restart_and_duplicate_fill(cloud, tmp_path):
    first, second = Wallet(tmp_path/'one.db'), Wallet(tmp_path/'two.db')
    price = Snapshot(price=50000, at=datetime.now(timezone.utc).isoformat())
    decision = Decision(action='buy', allocation_pct=100, up_pct=60, flat_pct=10, down_pct=30, reason='test', risks='test')
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda w: w.apply('same-request', 'test-model', price, decision), [first, second]))
    state = Wallet(tmp_path/'restart.db').state(price.price)
    assert 0 <= state['cash'] < 100 and len(state['history']) == 1
    assert state['equity'] <= 100000
    assert state['metrics']['recorded_steps'] == 1


def test_remote_transaction_rolls_back(cloud, tmp_path):
    engine = Engine(tmp_path/'paper.db')
    with pytest.raises(RuntimeError):
        with engine.db() as db:
            db.execute("UPDATE settings SET value='0' WHERE key='cash'")
            raise RuntimeError('abort')
    assert engine.snapshot()['cash'] == 1000000


def test_parameterized_news_and_cloud_comparison(cloud, tmp_path):
    engine = Engine(tmp_path/'paper.db')
    key = "malicious'); DROP TABLE news; --"
    engine.news(key, 'test title', 'https://example.com', '')
    assert engine.get_news(key)['id'] == key
    payload = {'ready': True, 'completed_stocks': 1, 'rows': [{'name': '삼성전자'}]}
    publish(payload)
    assert snapshot()['rows'] == payload['rows']
    assert snapshot()['dashboard_synced_at']


def test_encrypted_settings_persist_in_postgres(cloud,tmp_path):
    from cryptography.fernet import Fernet
    from app.settings import SettingsStore
    key=Fernet.generate_key()
    first=SettingsStore(tmp_path/'one-settings.db',key)
    value=dict(client_id='synthetic-client',client_secret='synthetic-secret',account_seq='synthetic-account',stream_enabled=False)
    first.save(value)
    second=SettingsStore(tmp_path/'two-settings.db',key)
    assert second.load()==value
    with second.database.db() as db:
        payload=db.execute("SELECT payload FROM account_integration_settings WHERE user_id='owner'").fetchone()['payload']
    assert 'synthetic-secret' not in payload and 'synthetic-account' not in payload
    assert not (tmp_path/'one-settings.db').exists()


def test_account_namespaces_and_credentials_persist_separately(cloud,tmp_path):
    import secrets
    from cryptography.fernet import Fernet
    from app.settings import SettingsStore
    auth=AuthStore(tmp_path/'auth.db');auth.configure('admin','admin-cloud-test-password')
    auth.add_user('second','second-cloud-test-password')
    user_id=auth.user_id('second')
    token=auth.login('second','second-cloud-test-password','account-isolation',3600)
    assert AuthStore(tmp_path/'restart.db').authenticate(token)=='second'
    key=Fernet.generate_key();store=SettingsStore(tmp_path/'settings.db',key)
    store.save({'client_id':'owner','client_secret':'owner-key'})
    store.save({'client_id':'second','client_secret':'second-key'},user_id)
    restored=SettingsStore(tmp_path/'restored-settings.db',key)
    assert restored.load()['client_secret']=='owner-key'
    assert restored.load(user_id)['client_secret']=='second-key'
    first=Engine(tmp_path/'first.db')
    second=Engine(tmp_path/'second.db',tenant=user_id)
    first.quote('005930',10000,0);first.order('005930','buy',2,'owner-cloud-order')
    assert second.snapshot()['orders']==[]
    second.quote('005930',10000,0);second.order('005930','buy',1,'second-cloud-order')
    assert first.snapshot()['cash']==980000
    assert Engine(tmp_path/'restored-second.db',tenant=user_id).snapshot()['cash']==990000
    first_wallet=Wallet(tmp_path/'first-ai.db');second_wallet=Wallet(tmp_path/'second-ai.db',tenant=user_id)
    first_wallet.reset(123456);second_wallet.reset(654321)
    assert first_wallet.state()['cash']==123456
    assert Wallet(tmp_path/'restored-second-ai.db',tenant=user_id).state()['cash']==654321


def test_us_wallet_persists_separately_from_domestic_and_other_accounts(cloud,tmp_path):
    domestic=Wallet(tmp_path/'domestic.db')
    us=Wallet(tmp_path/'us.db',namespace='ai_us',initially_paused=True)
    assert us.state()['paused']==1
    us.pause(False)
    quote=Snapshot(symbol='NVDA',price=170000,at=datetime.now(timezone.utc).isoformat())
    decision=Decision(action='buy',allocation_pct=100,up_pct=50,flat_pct=20,down_pct=30,reason='test',risks='test')
    us.apply('us-persist','test',quote,decision)
    restart=Wallet(tmp_path/'different.db',namespace='ai_us',initially_paused=True)
    assert len(restart.state()['history'])==1 and restart.state()['paused']==0
    assert 0<=restart.state()['cash']<100000
    assert domestic.state()['cash']==100000 and domestic.state()['history']==[]
    other=Wallet(tmp_path/'other.db',namespace='ai_us',tenant='b'*32,initially_paused=True)
    assert other.state()['cash']==100000 and other.state()['history']==[]
