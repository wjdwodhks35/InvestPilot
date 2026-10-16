"""Opt-in public research collection. No broker, orders, LLM or MCP imports."""
import asyncio
import base64
import gzip
import hashlib
import json
import os
import re
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from defusedxml import ElementTree
from app.integrations import parse_feed
from app.storage import Database


def flag(env, key):
    value = env.get(key, 'false').lower()
    if value not in ('true', 'false'):
        raise ValueError(key + ' must be true or false')
    return value == 'true'


def daily_bars(body, now=None):
    now = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo('Asia/Seoul'))
    root = ElementTree.fromstring(body)
    rows = {}
    for item in root.findall('.//item'):
        parts = item.attrib.get('data', '').split('|')
        if len(parts) != 6:
            raise ValueError('Invalid daily bar')
        day = datetime.strptime(parts[0], '%Y%m%d').date()
        if day > now.date() or (day == now.date() and (now.hour, now.minute) < (15, 30)):
            continue
        o, h, low, c, v = map(int, parts[1:])
        if min(o, h, low, c) <= 0 or v < 0 or h < max(o, low, c) or low > min(o, h, c):
            raise ValueError('Invalid OHLC')
        date = day.isoformat()
        if date in rows:
            raise ValueError('Duplicate date')
        rows[date] = dict(date=date, open=o, high=h, low=low, close=c, volume=v)
    if not rows or len(rows) > 1500:
        raise ValueError('Invalid daily history')
    return [rows[k] for k in sorted(rows)]


class CollectionStore:
    def __init__(self, path=None, database_url=None, clock=time.time, budget=32_000_000):
        self.clock, self.budget = clock, budget
        self.storage = Database(path or Path(os.getenv('INVESTPILOT_DATA_DIR', 'data'))/'collection.db',
                                'collection', database_url=database_url)
        with self.storage.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS collection_jobs (
                    name TEXT PRIMARY KEY, next_at REAL NOT NULL, lease_until REAL NOT NULL,
                    lease TEXT NOT NULL, last_success REAL, failures INTEGER NOT NULL, error TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS collection_artifacts (
                    digest TEXT PRIMARY KEY, category TEXT NOT NULL, payload TEXT NOT NULL,
                    size INTEGER NOT NULL, created_at REAL NOT NULL, uploaded_at REAL, remote_id TEXT NOT NULL);
            ''')

    def claim(self, name):
        now, lease = self.clock(), uuid.uuid4().hex
        with self.storage.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM collection_jobs WHERE name=?', (name,)).fetchone()
            if row and (row['next_at'] > now or row['lease_until'] > now):
                return None
            db.execute('INSERT INTO collection_jobs VALUES(?,?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET lease_until=excluded.lease_until,lease=excluded.lease',
                       (name, 0, now+3600, lease, None, 0, ''))
        return lease

    def finish(self, name, lease, interval, success):
        now = self.clock()
        with self.storage.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM collection_jobs WHERE name=? AND lease=?', (name, lease)).fetchone()
            if not row:
                return
            failures = 0 if success else row['failures']+1
            delay = interval if success else min(3600, 60 * 2**min(failures-1, 6))
            db.execute('UPDATE collection_jobs SET next_at=?,lease_until=0,lease=?,last_success=?,failures=?,error=? WHERE name=? AND lease=?',
                       (now+delay, '', now if success else row['last_success'], failures,
                        '' if success else 'collection_or_upload_failed', name, lease))

    def save(self, category, value):
        raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
        if len(raw) > 4_000_000:
            raise ValueError('Artifact too large')
        digest = hashlib.sha256(raw).hexdigest()
        payload = base64.b64encode(gzip.compress(raw, mtime=0)).decode()
        with self.storage.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM collection_artifacts WHERE digest=?', (digest,)).fetchone():
                return False
            # Only old acknowledged metadata is pruned. Pending data is never silently discarded.
            db.execute('DELETE FROM collection_artifacts WHERE uploaded_at IS NOT NULL AND uploaded_at<?', (self.clock()-180*86400,))
            used = db.execute('SELECT COALESCE(SUM(size),0) AS used FROM collection_artifacts').fetchone()['used']
            count = db.execute('SELECT COUNT(*) AS n FROM collection_artifacts').fetchone()['n']
            if count >= 10000:
                old = db.execute('SELECT digest FROM collection_artifacts WHERE uploaded_at IS NOT NULL ORDER BY uploaded_at LIMIT 100').fetchall()
                for row in old:
                    db.execute('DELETE FROM collection_artifacts WHERE digest=?', (row['digest'],))
                count -= len(old)
            if used+len(payload) > self.budget or count >= 10000:
                raise ValueError('Collection spool full')
            db.execute('INSERT INTO collection_artifacts VALUES(?,?,?,?,?,?,?)',
                       (digest, category, payload, len(payload), self.clock(), None, ''))
        return True

    def pending(self):
        with self.storage.db() as db:
            return db.execute('SELECT * FROM collection_artifacts WHERE uploaded_at IS NULL ORDER BY created_at,digest LIMIT 3').fetchall()

    def uploaded(self, digest, remote_id):
        if not isinstance(remote_id, str) or not remote_id:
            raise ValueError('Drive acknowledgement required')
        with self.storage.db() as db:
            db.execute('UPDATE collection_artifacts SET uploaded_at=?,remote_id=?,payload=?,size=0 WHERE digest=?',
                       (self.clock(), remote_id, '', digest))

    def status(self):
        with self.storage.db() as db:
            jobs = db.execute('SELECT name,next_at,last_success,failures,error,lease_until FROM collection_jobs ORDER BY name').fetchall()
            summary = db.execute('SELECT COUNT(*) AS total,COALESCE(SUM(size),0) AS pending_bytes FROM collection_artifacts').fetchone()
            pending = db.execute('SELECT COUNT(*) AS n FROM collection_artifacts WHERE uploaded_at IS NULL').fetchone()['n']
        return dict(jobs=[dict(row) for row in jobs], artifacts=summary['total'],
                    pending=pending, pending_bytes=summary['pending_bytes'])


class Collector:
    def __init__(self, env=None, store=None, client=None, news_service=None, drive_factory=None):
        env = os.environ if env is None else env
        self.enabled = flag(env, 'INVESTPILOT_COLLECTION_ENABLED')
        self.drive_enabled = flag(env, 'INVESTPILOT_COLLECTION_DRIVE_ENABLED')
        self.store, self.client, self.news_service = store, client, news_service
        self.feeds = [x.strip() for x in env.get('NEWS_RSS_URLS', '').split(',') if x.strip()]
        self.symbols = list(dict.fromkeys(filter(None, env.get('INVESTPILOT_COLLECTION_SYMBOLS', '').split(','))))
        if len(self.symbols) > 50 or any(not re.fullmatch(r'\d{6}', s) for s in self.symbols):
            raise ValueError('Configure at most 50 six-digit KR symbols')
        if len(self.feeds) > 20:
            raise ValueError('At most 20 feeds supported')
        self.price_interval = max(3600, int(env.get('INVESTPILOT_COLLECTION_PRICE_SECONDS', '86400')))
        self.news_interval = max(60, int(env.get('NEWS_POLL_SECONDS', '300')))
        self.drive_factory = drive_factory
        self.credentials = None
        if self.enabled and env.get('RENDER') == 'true' and not env.get('INVESTPILOT_DATABASE_URL'):
            raise ValueError('Render collection requires persistent PostgreSQL')
        if self.enabled and self.store is None:
            self.store = CollectionStore()

    def status(self):
        return dict(enabled=self.enabled, drive_enabled=self.drive_enabled,
                    symbols=len(self.symbols), feeds=len(self.feeds),
                    **(self.store.status() if self.enabled else {}))

    async def fetch(self, client, url):
        async with client.stream('GET', url) as response:
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 2_000_000:
                    raise ValueError('Response too large')
        return bytes(body)

    async def tick(self):
        if not self.enabled:
            return
        if self.client is not None:
            await self.collect(self.client)
        else:
            async with httpx.AsyncClient(timeout=20, trust_env=False, follow_redirects=False) as client:
                await self.collect(client)
        if self.drive_enabled:
            task = asyncio.create_task(asyncio.to_thread(self.upload))
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                await task
                raise

    async def collect(self, client):
        for category, sources, interval in [('prices', self.symbols, self.price_interval), ('news', self.feeds, self.news_interval)]:
            for index, source in enumerate(sources):
                name = category+':'+(source if category == 'prices' else str(index+1))
                lease = await asyncio.to_thread(self.store.claim, name)
                if lease is None:
                    continue
                success = False
                try:
                    url = ('https://fchart.stock.naver.com/sise.nhn?symbol='+source+'&timeframe=day&count=1500&requestType=0'
                           if category == 'prices' else source)
                    if not url.startswith(('https://', 'http://')):
                        raise ValueError('Invalid source')
                    body = await asyncio.wait_for(self.fetch(client, url), timeout=30)
                    rows = daily_bars(body) if category == 'prices' else parse_feed(body, 'feed-'+str(index+1))
                    value = dict(version=1, category=category, source=source if category=='prices' else 'feed-'+str(index+1),
                                 rows=rows, raw_sha256=hashlib.sha256(body).hexdigest())
                    # Preserve the public raw price source; RSS can contain private feed URLs, so archive normalized articles only.
                    if category == 'news':
                        value.pop('raw_sha256')
                        value['rows'] = sorted(rows, key=lambda row: row['id'])
                    if category == 'prices':
                        value['raw_base64'] = base64.b64encode(body).decode()
                    await asyncio.to_thread(self.store.save, category, value)
                    if category == 'news' and self.news_service:
                        for row in rows:
                            await asyncio.to_thread(self.news_service.engine.ingest_news, row)
                    success = True
                except asyncio.CancelledError:
                    raise
                except Exception:
                    pass  # Only fixed error codes are persisted; never provider bodies, URLs or credentials.
                finally:
                    await asyncio.to_thread(self.store.finish, name, lease, interval, success)

    def upload(self):
        lease = self.store.claim('drive')
        if lease is None:
            return
        success = False
        storage = None
        try:
            if self.drive_factory:
                storage = self.drive_factory()
            else:
                from app.experiments.storage import DriveStorage, DriveCredentials
                if self.credentials is None:
                    self.credentials = DriveCredentials()
                storage = DriveStorage(credentials=self.credentials)
            for artifact in self.store.pending():
                with tempfile.TemporaryDirectory(prefix='investpilot-collection-') as directory:
                    path = Path(directory)/(artifact['digest']+'.jsonl.gz')
                    path.write_bytes(base64.b64decode(artifact['payload']))
                    result = storage.upload(path, artifact['category'], artifact_id=artifact['digest'])
                    self.store.uploaded(artifact['digest'], result.get('id'))
            success = True
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401 and self.credentials is not None:
                self.credentials.cached = None
        except Exception:
            pass
        finally:
            if storage:
                storage.client.close()
            self.store.finish('drive', lease, 60, success)

    async def loop(self):
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                # DB outage must not crash the web server or log connection details.
                pass
            await asyncio.sleep(60)
