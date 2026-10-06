"""Persistent paper trading. Monetary amounts use integer KRW throughout."""
import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager
from decimal import Decimal
import threading

WATCHLIST = [
    ('005930', '삼성전자', 'AI 반도체'),
    ('053800', '안랩', '사이버보안'), ('263860', '지니언스', '사이버보안'),
    ('417310', '샌즈랩', '사이버보안'), ('010120', 'LS ELECTRIC', 'AI 전력'),
    ('267260', 'HD현대일렉트릭', 'AI 전력'),
]
DEFAULT_RULES = dict(take_profit=15, stop_loss=7, trailing_stop=5,
                     trailing_activation=10, max_order=100000, daily_buy_limit=200000,
                     surge_limit=15, paused=False)

class Engine:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        self.trade_lock = threading.RLock()
        with self.db() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE IF NOT EXISTS quotes(symbol TEXT PRIMARY KEY,price INTEGER,change REAL,at TEXT);
            CREATE TABLE IF NOT EXISTS positions(symbol TEXT PRIMARY KEY,qty INTEGER,cost INTEGER,peak INTEGER);
            CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY,symbol TEXT,side TEXT,qty INTEGER,price INTEGER,reason TEXT,at TEXT);
            CREATE TABLE IF NOT EXISTS news(id TEXT PRIMARY KEY,title TEXT,url TEXT,symbol TEXT,analysis TEXT,at TEXT);
            ''')
            c.executescript('''
            CREATE TABLE IF NOT EXISTS price_history(id INTEGER PRIMARY KEY, symbol TEXT,price INTEGER,at TEXT);
            CREATE INDEX IF NOT EXISTS history_symbol ON price_history(symbol,id);
            CREATE TABLE IF NOT EXISTS market_quotes(symbol TEXT PRIMARY KEY,price INTEGER,at TEXT);
            CREATE TABLE IF NOT EXISTS market_history(id INTEGER PRIMARY KEY,symbol TEXT,price INTEGER,at TEXT);
            CREATE TABLE IF NOT EXISTS news_metadata(id TEXT PRIMARY KEY,source TEXT,published_at TEXT);
            ''')
            for key, value in [('cash', 1000000), ('rules', DEFAULT_RULES)]:
                c.execute('INSERT OR IGNORE INTO settings VALUES (?,?)', (key, json.dumps(value)))

    @contextmanager
    def db(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        try:
            with c:
                yield c
        finally:
            c.close()

    def setting(self, c, key):
        return json.loads(c.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()[0])

    def rules(self, rules):
        with self.db() as c:
            c.execute('UPDATE settings SET value=? WHERE key="rules"', (json.dumps(rules),))

    def snapshot(self):
        with self.db() as c:
            positions = []
            for row in c.execute('SELECT p.*,q.price,q.at FROM positions p LEFT JOIN quotes q USING(symbol)'):
                p = dict(row)
                p['return_pct'] = round((p['price'] * p['qty'] / p['cost'] - 1) * 100, 2) if p['price'] else None
                positions.append(p)
            return dict(mode='paper', price_source='manual', broker_connected=False,
                cash=self.setting(c, 'cash'), rules=self.setting(c, 'rules'),
                positions=positions, quotes=[dict(x) for x in c.execute('SELECT * FROM quotes')],
                orders=[dict(x) for x in c.execute('SELECT * FROM orders ORDER BY at DESC LIMIT 100')],
                news=[dict(x) for x in c.execute('SELECT n.*,m.source,m.published_at FROM news n LEFT JOIN news_metadata m USING(id) ORDER BY n.at DESC LIMIT 50')],
                watchlist=[dict(symbol=s, name=n, theme=t) for s,n,t in WATCHLIST])

    def _order(self, symbol, side, qty, request_id, reason='수동 가상 주문'):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            existing = c.execute('SELECT * FROM orders WHERE id=?', (request_id,)).fetchone()
            if existing:
                if (existing['symbol'], existing['side'], existing['qty']) != (symbol, side, qty):
                    raise ValueError('같은 요청 ID에 다른 주문을 사용할 수 없습니다')
                return dict(existing)
            rules = self.setting(c, 'rules')
            if rules['paused']: raise ValueError('긴급 정지 중입니다')
            q = c.execute('SELECT * FROM quotes WHERE symbol=?', (symbol,)).fetchone()
            if not q: raise ValueError('가격을 먼저 입력하세요')
            age = (datetime.now(timezone.utc)-datetime.fromisoformat(q['at'])).total_seconds()
            if age > 60: raise ValueError('가격이 60초 이상 경과했습니다. 갱신하세요')
            amount = q['price'] * qty
            cash = self.setting(c, 'cash')
            p = c.execute('SELECT * FROM positions WHERE symbol=?', (symbol,)).fetchone()
            now = datetime.now(timezone.utc)
            if side == 'buy':
                if amount > rules['max_order']: raise ValueError('주문금액 한도 초과')
                if q['change'] >= rules['surge_limit']: raise ValueError('급등 신규매수 제한')
                spent = c.execute("SELECT COALESCE(SUM(qty*price),0) FROM orders WHERE side='buy' AND date(at,'+9 hours')=date(?,'+9 hours')", (now.isoformat(),)).fetchone()[0]
                if spent + amount > rules['daily_buy_limit']: raise ValueError('일일 매수금액 한도 초과')
                if cash < amount: raise ValueError('가상 현금 부족')
                c.execute('INSERT OR REPLACE INTO positions VALUES (?,?,?,?)',
                    (symbol, (p['qty'] if p else 0)+qty, (p['cost'] if p else 0)+amount, max(p['peak'] if p else 0,q['price'])))
                cash -= amount
            else:
                if not p or qty > p['qty']: raise ValueError('보유수량 부족')
                remaining = p['qty']-qty
                if remaining:
                    c.execute('UPDATE positions SET qty=?,cost=? WHERE symbol=?', (remaining, p['cost']*remaining//p['qty'], symbol))
                else: c.execute('DELETE FROM positions WHERE symbol=?', (symbol,))
                cash += amount
            c.execute('UPDATE settings SET value=? WHERE key="cash"', (json.dumps(cash),))
            c.execute('INSERT INTO orders VALUES (?,?,?,?,?,?,?)', (request_id,symbol,side,qty,q['price'],reason,now.isoformat()))
            return dict(c.execute('SELECT * FROM orders WHERE id=?',(request_id,)).fetchone())

    def order(self, *args, **kwargs):
        with self.trade_lock:
            return self._order(*args, **kwargs)

    def quote(self, *args, **kwargs):
        with self.trade_lock:
            return self._quote(*args, **kwargs)

    def _quote(self, symbol, price, change):
        now = datetime.now(timezone.utc).isoformat()
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('INSERT OR REPLACE INTO quotes VALUES (?,?,?,?)',(symbol,price,change,now))
            c.execute('INSERT INTO price_history(symbol,price,at) VALUES (?,?,?)',(symbol,price,now))
            c.execute('DELETE FROM price_history WHERE symbol=? AND id NOT IN (SELECT id FROM price_history WHERE symbol=? ORDER BY id DESC LIMIT 2000)',(symbol,symbol))
            p = c.execute('SELECT * FROM positions WHERE symbol=?',(symbol,)).fetchone()
            rules = self.setting(c, 'rules')
            reason = None
            if p:
                peak = max(p['peak'],price)
                c.execute('UPDATE positions SET peak=? WHERE symbol=?',(peak,symbol))
                gain = (Decimal(price*p['qty'])/p['cost']-1)*100
                peak_gain = (Decimal(peak*p['qty'])/p['cost']-1)*100
                if gain <= -rules['stop_loss']: reason='손절'
                elif gain >= rules['take_profit']: reason='목표수익 도달'
                elif peak_gain >= rules['trailing_activation'] and (1-Decimal(price)/peak)*100 >= rules['trailing_stop']: reason='트레일링 스톱'
        # Paper executions revalidate current quote and position under a transaction.
        if reason and not rules['paused']:
            return self.order(symbol,'sell',p['qty'],f'auto-{symbol}-{now}',reason)
        return dict(symbol=symbol,price=price,reason=reason)

    def news(self, news_id, title, url, symbol):
        matched = [n for s,n,t in WATCHLIST if n.lower() in title.lower()]
        terms = [x for x in ['해킹','침해','보안','수주','실적','전력','데이터센터','규제'] if x in title]
        analysis = json.dumps(dict(method='keyword', matched=matched, keywords=terms,
            important=bool(terms), judgment='검토 필요', note='키워드 분류이며 AI 투자 판단 또는 매매 신호가 아닙니다'),ensure_ascii=False)
        with self.db() as c:
            c.execute('INSERT OR IGNORE INTO news VALUES (?,?,?,?,?,?)',
                (news_id,title,url,symbol,analysis,datetime.now(timezone.utc).isoformat()))
        return json.loads(analysis)

    def history(self, symbol):
        with self.db() as c:
            return [dict(r) for r in c.execute('SELECT price,at FROM (SELECT id,price,at FROM price_history WHERE symbol=? ORDER BY id DESC LIMIT 300) ORDER BY id',(symbol,))]

    def ingest_news(self, item):
        with self.db() as c:
            exists=c.execute('SELECT 1 FROM news WHERE id=?',(item['id'],)).fetchone()
        if exists: return False
        self.news(item['id'],item['title'],item['url'],'')
        with self.db() as c:
            c.execute('INSERT OR IGNORE INTO news_metadata VALUES (?,?,?)',(item['id'],item['source'],item['published_at']))
        return True

    def get_news(self, news_id):
        with self.db() as c:
            row=c.execute('SELECT * FROM news WHERE id=?',(news_id,)).fetchone()
            return dict(row) if row else None

    def save_analysis(self, news_id, analysis):
        with self.db() as c:
            c.execute('UPDATE news SET analysis=? WHERE id=?',(json.dumps(analysis,ensure_ascii=False),news_id))

    def market_tick(self,symbol,price,at):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT at FROM market_quotes WHERE symbol=?',(symbol,)).fetchone()
            if old and old['at']>=at:return
            c.execute('INSERT OR REPLACE INTO market_quotes VALUES (?,?,?)',(symbol,price,at))
            c.execute('INSERT INTO market_history(symbol,price,at) VALUES (?,?,?)',(symbol,price,at))
            c.execute('DELETE FROM market_history WHERE symbol=? AND id NOT IN (SELECT id FROM market_history WHERE symbol=? ORDER BY id DESC LIMIT 2000)',(symbol,symbol))

    def market_state(self):
        with self.db() as c:return [dict(x) for x in c.execute('SELECT * FROM market_quotes')]

    def market_history(self,symbol):
        with self.db() as c:return [dict(x) for x in c.execute('SELECT price,at FROM (SELECT id,price,at FROM market_history WHERE symbol=? ORDER BY id DESC LIMIT 300) ORDER BY id',(symbol,))]
