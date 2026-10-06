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
