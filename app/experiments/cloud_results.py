"""Persist a dashboard copy; original experiment archives remain in Drive."""
import json
from datetime import datetime, timezone
from app.storage import Database


def database():
    store = Database('data/cloud-results.db', 'results')
    if not store.remote:
        raise ValueError('External database must be configured to publish results')
    with store.db() as connection:
        connection.executescript('CREATE TABLE IF NOT EXISTS comparison_snapshot(id INTEGER PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL);')
    return store


def publish(payload):
    if not payload.get('ready'):
        raise ValueError('No comparison results to publish')
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    if len(encoded.encode()) > 5 * 1024 * 1024:
        raise ValueError('Dashboard snapshot exceeds 5 MB')
    with database().db() as connection:
        connection.execute('INSERT INTO comparison_snapshot VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at',
                           (encoded, datetime.now(timezone.utc).isoformat()))


def read():
    with database().db() as connection:
        row = connection.execute('SELECT payload,updated_at FROM comparison_snapshot WHERE id=1').fetchone()
    if not row:
        return {'ready': False, 'message': '저장된 예측 결과가 없습니다. Drive 결과를 DB에 동기화하세요.'}
    result = json.loads(row['payload'])
    result['dashboard_synced_at'] = row['updated_at']
    return result
