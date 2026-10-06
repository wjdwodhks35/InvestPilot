import tempfile
import unittest
from pathlib import Path
from app.engine import Engine, DEFAULT_RULES

class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.e=Engine(Path(self.tmp.name)/'test.db')
        self.e.quote('053800',10000,0)
    def tearDown(self): self.tmp.cleanup()
    def buy(self,qty=5,key='request-1'): return self.e.order('053800','buy',qty,key)
    def test_idempotent_order_and_persistence(self):
        self.buy(); self.buy()
        self.assertEqual(self.e.snapshot()['cash'],950000)
        self.assertEqual(len(self.e.snapshot()['orders']),1)
        self.assertEqual(Engine(self.e.path).snapshot()['positions'][0]['qty'],5)
        with self.assertRaises(ValueError):self.buy(6)
    def test_stop_loss_sells_once(self):
        self.buy();self.e.quote('053800',9000,0);self.e.quote('053800',9000,0)
        self.assertEqual(self.e.snapshot()['positions'],[])
        self.assertEqual(self.e.snapshot()['cash'],995000)
        self.assertEqual(len(self.e.snapshot()['orders']),2)
    def test_take_profit_and_trailing(self):
        self.buy(); self.e.quote('053800',11500,0)
        self.assertEqual(self.e.snapshot()['positions'],[])
        self.e.quote('053800',10000,0);self.buy(key='request-2')
        self.e.quote('053800',11200,0);self.e.quote('053800',10500,0)
        self.assertEqual(self.e.snapshot()['orders'][0]['reason'],'트레일링 스톱')
    def test_limits_and_pause(self):
        with self.assertRaises(ValueError):self.buy(11)
        self.e.quote('053800',10000,20)
        with self.assertRaises(ValueError):self.buy()
        self.e.quote('053800',10000,0)
        self.e.rules({**DEFAULT_RULES,'paused':True})
        with self.assertRaises(ValueError):self.buy()
    def test_daily_limit_and_oversell(self):
        self.buy(10);self.buy(10,'request-2')
        with self.assertRaises(ValueError):self.buy(1,'request-3')
        with self.assertRaises(ValueError):self.e.order('053800','sell',21,'sell-req')
    def test_stale_price(self):
        with self.e.db() as c:c.execute("UPDATE quotes SET at='2020-01-01T00:00:00+00:00'")
        with self.assertRaises(ValueError):self.buy()
    def test_news_dedup(self):
        for _ in range(2):self.e.news('news-123','안랩 보안 수주','','053800')
        self.assertEqual(len(self.e.snapshot()['news']),1)

if __name__=='__main__':unittest.main()
