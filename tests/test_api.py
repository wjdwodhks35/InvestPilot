import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from app import main
from app.engine import Engine

class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.old=main.engine
        main.engine=Engine(Path(self.tmp.name)/'api.db')
        self.client=TestClient(main.app)
    def tearDown(self):
        self.client.close()
        main.engine=self.old
        self.tmp.cleanup()
    def test_home_and_complete_trade(self):
        self.assertEqual(self.client.get('/').status_code,200)
        self.assertEqual(self.client.post('/api/quotes',json={'symbol':'053800','price':10000,'change':0}).status_code,200)
        order={'symbol':'053800','side':'buy','qty':5,'request_id':'api-order-1'}
        self.assertEqual(self.client.post('/api/orders',json=order).status_code,200)
        self.client.post('/api/orders',json=order)
        self.assertEqual(self.client.get('/api/state').json()['cash'],950000)
        self.client.post('/api/quotes',json={'symbol':'053800','price':9000,'change':0})
        self.assertEqual(self.client.get('/api/state').json()['positions'],[])
    def test_invalid_input_and_unknown_quote(self):
        self.assertEqual(self.client.post('/api/quotes',json={'symbol':'053800','price':0,'change':0}).status_code,422)
        self.assertEqual(self.client.post('/api/orders',json={'symbol':'053800','side':'buy','qty':1,'request_id':'unknown-price'}).status_code,409)
    def test_news(self):
        response=self.client.post('/api/news',json={'news_id':'api-news-1','title':'안랩 보안 수주'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['method'],'keyword')
