"""Durable MCP user bindings and limits; shared SQLite/PostgreSQL transactions."""
import hashlib
import json
import time

class MCPAccess:
    def __init__(self, auth_store, clock=time.time):
        self.store, self.clock = auth_store, clock
        with self.store.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS mcp_links (
                    principal TEXT PRIMARY KEY, user_id TEXT UNIQUE NOT NULL);
                CREATE TABLE IF NOT EXISTS mcp_limits (
                    bucket TEXT PRIMARY KEY, window INTEGER NOT NULL, used INTEGER NOT NULL);
            """)

    @staticmethod
    def principal(issuer, subject):
        if not isinstance(subject, str) or not 1 <= len(subject) <= 256:
            raise ValueError('Invalid subject')
        return hashlib.sha256(json.dumps([issuer, subject], separators=(',', ':')).encode()).hexdigest()

    def link(self, issuer, subject, username):
        user_id = self.store.user_id(username)
        if not user_id:
            raise ValueError('Existing InvestPilot user required')
        principal = self.principal(issuer, subject)
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT user_id FROM mcp_links WHERE principal=?', (principal,)).fetchone()
            if existing and existing['user_id'] != user_id:
                raise ValueError('Identity already linked; revoke first')
            db.execute('DELETE FROM mcp_links WHERE user_id=?', (user_id,))
            db.execute('INSERT INTO mcp_links VALUES (?,?) ON CONFLICT(principal) DO UPDATE SET user_id=excluded.user_id',
                       (principal, user_id))

    def revoke(self, username):
        user_id = self.store.user_id(username)
        with self.store.db() as db:
            db.execute('DELETE FROM mcp_links WHERE user_id=?', (user_id,))

    def identity(self, issuer, subject):
        principal = self.principal(issuer, subject)
        with self.store.db() as db:
            row = db.execute('SELECT mcp_links.user_id FROM mcp_links JOIN users ON users.id=mcp_links.user_id WHERE principal=?',
                             (principal,)).fetchone()
        return row['user_id'] if row else None

    def reserve(self, user_id=None):
        # No payload or credential is stored. Counts survive restart and all workers.
        now = int(self.clock())
        buckets = [('global:minute', now // 60, 120)]
        if user_id is not None:
            buckets += [('user:minute:' + user_id, now // 60, 20),
                        ('user:day:' + user_id, now // 86400, 500)]
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            pending = []
            for key, window, limit in buckets:
                row = db.execute('SELECT window,used FROM mcp_limits WHERE bucket=?', (key,)).fetchone()
                used = row['used'] if row and row['window'] == window else 0
                if used >= limit:
                    return False
                pending.append((key, window, used + 1))
            for values in pending:
                db.execute('INSERT INTO mcp_limits VALUES (?,?,?) ON CONFLICT(bucket) DO UPDATE SET window=excluded.window,used=excluded.used',
                           values)
        return True
