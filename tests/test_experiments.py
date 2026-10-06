import unittest
from fastapi.testclient import TestClient
from app.main import app

class LabTests(unittest.TestCase):
    def setUp(self): self.client=TestClient(app)
    def tearDown(self): self.client.close()
    def inspect(self,rows):
        return self.client.post('/api/experiments/inspect',json={'csv_text':'timestamp,symbol,close,volume,news_title,news_published_at\n'+rows})
    def test_separate_page_and_no_trading(self):
        self.assertEqual(self.client.get('/lab').status_code,200)
        self.assertFalse(self.client.get('/api/experiments/status').json()['trading_connected'])
        before=self.client.get('/api/state').json()
        r=self.inspect('2025-01-02T16:00:00+09:00,053800,10000,100,수주,2025-01-02T10:00:00+09:00')
        self.assertEqual(r.status_code,200)
        self.assertEqual(self.client.get('/api/state').json(),before)
    def test_future_news_and_missing_timezone(self):
        self.assertEqual(self.inspect('2025-01-02T16:00:00+09:00,053800,10000,100,수주,2025-01-03T10:00:00+09:00').status_code,422)
        self.assertEqual(self.inspect('2025-01-02T16:00:00,053800,10000,100,,').status_code,422)
    def test_duplicate_and_nan(self):
        row='2025-01-02T16:00:00+09:00,053800,10000,100,,'
        self.assertEqual(self.inspect(row+'\n'+row).status_code,422)
        self.assertEqual(self.inspect(row.replace('10000','nan')).status_code,422)
