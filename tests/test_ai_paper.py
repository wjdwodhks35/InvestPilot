import asyncio
import json
import os
import tempfile
import unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch
import httpx
from app.experiments.ai_paper import Wallet,Snapshot,Decision,OllamaExperiment

class AiPaperTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.w=Wallet(Path(self.tmp.name)/'ai.db')
    def tearDown(self):self.tmp.cleanup()
    def snapshot(self,price=10000):return Snapshot(price=price,at=datetime.now(timezone.utc).isoformat())
    def decision(self,action,allocation=100):return Decision(action=action,allocation_pct=allocation,up_pct=50,flat_pct=20,down_pct=30,reason='테스트',risks='실험용')
    def test_rolls_profits_and_losses_no_additional_cash(self):
        self.w.apply('buy-1','test',self.snapshot(),self.decision('buy'))
        self.w.apply('sell-1','test',self.snapshot(9000),self.decision('sell'))
        cash=self.w.state()['cash'];self.assertLess(cash,100000)
        self.w.apply('buy-2','test',self.snapshot(9000),self.decision('buy'))
        self.w.apply('sell-2','test',self.snapshot(12000),self.decision('sell'))
        self.assertGreater(self.w.state()['cash'],100000)
        self.assertEqual(self.w.state()['initial'],100000)
    def test_fractional_budget_and_idempotency(self):
        s=self.snapshot(270000);d=self.decision('buy')
        self.w.apply('request-1','test',s,d);self.w.apply('request-1','test',s,d)
        w=self.w.state(270000)
        self.assertGreater(w['shares'],0);self.assertLess(w['shares'],1)
        self.assertGreaterEqual(w['cash'],0);self.assertEqual(len(w['history']),1)
        self.assertLessEqual(w['equity'],100000)
    def test_pause_stale_data_and_invalid_probability(self):
        self.w.pause(True)
        with self.assertRaises(ValueError):self.w.apply('request','test',self.snapshot(),self.decision('buy'))
        with self.assertRaises(ValueError):Snapshot(price=10000,at=(datetime.now(timezone.utc)-timedelta(seconds=90)).isoformat())
        with self.assertRaises(ValueError):Decision(action='hold',allocation_pct=0,up_pct=90,flat_pct=90,down_pct=90,reason='test',risks='test')
    def test_model_response_and_future_news_filter(self):
        async def scenario():
            exp=OllamaExperiment(self.w);s=self.snapshot()
            s.news=[{'title':'future news','published_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()}]
            def handler(req):
                body=json.loads(req.content)
                ctx=json.loads(body['messages'][1]['content'])
                self.assertEqual(ctx['news'],[])
                self.assertNotIn('tools',body)
                self.assertEqual(body['model'],'qwen3:4b')
                return httpx.Response(200,json={'done':True,'message':{'content':self.decision('buy',50).model_dump_json()}})
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
                await exp.step('ollama-1',s,c)
            self.assertEqual(len(self.w.state()['history']),1)
            self.assertGreater(self.w.state()['cash'],49000)
        with patch.dict(os.environ,{'OLLAMA_MODEL':'qwen3:4b','OLLAMA_BASE_URL':'http://127.0.0.1:11434'}):asyncio.run(scenario())
    def test_invalid_response_never_executes(self):
        async def scenario():
            exp=OllamaExperiment(self.w)
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'done':True,'message':{'content':'not json'}}))) as c:
                with self.assertRaises(ValueError):await exp.step('invalid-1',self.snapshot(),c)
            self.assertEqual(self.w.state()['cash'],100000)
        asyncio.run(scenario())
    def test_no_remote_or_cloud_model(self):
        with patch.dict(os.environ,{'OLLAMA_BASE_URL':'https://api.example.com'}):
            with self.assertRaises(ValueError):OllamaExperiment(self.w)
    def test_ai_api_isolated_and_auto_requires_live_quote(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.experiments.ai_api import create_ai_router
        exp=OllamaExperiment(self.w)
        async def connected():return {'connected':True,'installed':True}
        exp.connection=connected
        async def decide(snapshot,client=None):return self.decision('hold',0)
        exp.decide=decide
        app=FastAPI();app.include_router(create_ai_router(exp,lambda:None))
        with TestClient(app) as c:
            self.assertEqual(c.put('/api/experiments/ai/automatic',json={'enabled':True}).status_code,409)
            r=c.post('/api/experiments/ai/step',json={'request_id':'api-test-1','price':270000})
            self.assertEqual(r.status_code,200)
            self.assertEqual(c.get('/api/experiments/ai/state').json()['wallet']['cash'],100000)
            c.put('/api/experiments/ai/pause',json={'enabled':True})
            self.assertEqual(c.post('/api/experiments/ai/step',json={'request_id':'api-test-2','price':270000}).status_code,409)
    def test_peer_context_uses_completed_data_only(self):
        import csv
        from app.experiments.ai_api import technical_context
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'peer.csv'
            with p.open('w') as f:
                writer=csv.writer(f);writer.writerow(['date','close','volume'])
                for day in range(1,26):writer.writerow([f'2026-09-{day:02d}',10000+day*10,1000])
                writer.writerow(['2026-09-26',999999,999999])
            context=technical_context('2026-09-26T14:00:00+09:00',p)
            self.assertEqual(context['as_of'],'2026-09-25')
            self.assertLess(context['ma5'],11000)
    def test_performance_metrics_after_simulated_roundtrip(self):
        self.w.apply('buy-test','test',self.snapshot(10000),self.decision('buy'))
        self.w.apply('sell-test','test',self.snapshot(9000),self.decision('sell'))
        metrics=self.w.state(9000)['metrics']
        self.assertEqual(metrics['recorded_steps'],2)
        self.assertLess(metrics['return_pct'],0)
        self.assertAlmostEqual(metrics['buy_hold_return_pct'],-10)
        self.assertGreater(metrics['sampled_max_drawdown_pct'],10)
