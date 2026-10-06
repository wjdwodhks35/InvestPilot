import asyncio
import os
import tempfile
import unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch
import httpx
from app.engine import Engine
from app.broker import TossBroker

class BrokerTests(unittest.TestCase):
    def test_auth_cached_and_account_header(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'TOSS_CLIENT_ID':'client','TOSS_CLIENT_SECRET':'secret','TOSS_ACCOUNT_SEQ':'1'}):
                b=TossBroker(Engine(Path(tmp)/'db'));calls=[]
                def handler(req):
                    calls.append(req)
                    if req.url.path=='/oauth2/token':
                        self.assertIn(b'grant_type=client_credentials',req.content)
                        return httpx.Response(200,json={'access_token':'token','expires_in':3600})
                    self.assertEqual(req.headers['X-Tossinvest-Account'],'1')
                    self.assertEqual(req.headers['Authorization'],'Bearer token')
                    return httpx.Response(200,json={'result':{'items':[]}})
                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
                    await b.read('/api/v1/holdings',True,c)
                    await b.read('/api/v1/holdings',True,c)
                self.assertEqual(sum(r.url.path=='/oauth2/token' for r in calls),1)
        asyncio.run(scenario())
    def test_tick_stale_replay_and_no_paper_orders(self):
        with tempfile.TemporaryDirectory() as tmp:
            e=Engine(Path(tmp)/'db');b=TossBroker(e)
            now=datetime.now(timezone.utc)
            def frame(t,p='10000'):return {'type':'message','topic':'trade:kr:053800','data':{'price':p,'timestamp':t.isoformat(),'currency':'KRW'}}
            b.consume(frame(now))
            b.consume(frame(now-timedelta(seconds=1),'9000'))
            b.consume(frame(now-timedelta(seconds=90),'5000'))
            self.assertEqual(e.market_state()[0]['price'],10000)
            self.assertEqual(len(e.market_history('053800')),1)
            self.assertEqual(e.snapshot()['quotes'],[])
            self.assertEqual(e.snapshot()['orders'],[])
    def test_missing_credentials_and_read_only(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'TOSS_CLIENT_ID':'','TOSS_CLIENT_SECRET':''}):
                b=TossBroker(Engine(Path(tmp)/'db'))
                with self.assertRaises(ValueError):await b.read('/api/v1/orders')
                async with httpx.AsyncClient(trust_env=False) as c:
                    with self.assertRaises(ValueError):await b.access_token(c)
        asyncio.run(scenario())
