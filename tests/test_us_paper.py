from datetime import datetime,timezone,timedelta
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from app.experiments.ai_paper import Wallet,Decision
from app.experiments.us_paper import us_snapshot,create_us_router

def market():
    now=datetime.now(timezone.utc)
    prices=[{'symbol':'NVDA','currency':'USD','lastPrice':'120.125','timestamp':now.isoformat()}]
    fx={'baseCurrency':'USD','quoteCurrency':'KRW','rate':'1400','validFrom':(now-timedelta(seconds=1)).isoformat(),'validUntil':(now+timedelta(seconds=59)).isoformat()}
    return prices,fx

def test_us_currency_conversion_and_quote_freshness():
    prices,fx=market();s=us_snapshot(prices,fx)
    assert s.symbol=='NVDA' and s.price==168175
    assert s.indicators['price_usd']=='120.125'
    prices[0]['timestamp']=(datetime.now(timezone.utc)-timedelta(seconds=90)).isoformat()
    with pytest.raises(ValueError):us_snapshot(prices,fx)
    prices,fx=market();fx['quoteCurrency']='USD'
    with pytest.raises(ValueError):us_snapshot(prices,fx)
    prices,fx=market();fx['validUntil']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError):us_snapshot(prices,fx)

def test_us_wallet_isolation_budget_context_and_pause(tmp_path):
    domestic=Wallet(tmp_path/'kr.db')
    us=Wallet(tmp_path/'us.db',namespace='ai_us',initially_paused=True)
    other=Wallet(tmp_path/'other.db',namespace='ai_us',tenant='a'*32,initially_paused=True)
    async def provider():return market()
    app=FastAPI();app.include_router(create_us_router(lambda:us,provider))
    c=TestClient(app)
    assert c.get('/api/experiments/us/worker-context').status_code==409
    c.put('/api/experiments/us/pause',json={'enabled':False})
    ctx=c.get('/api/experiments/us/worker-context').json()
    assert ctx['snapshot']['symbol']=='NVDA'
    assert c.post('/api/experiments/us/worker-decision',json={'request_id':'spoof-attempt','context_id':'f'*32,'model':'qwen3:4b','decision':Decision(action='hold',allocation_pct=0,up_pct=50,flat_pct=20,down_pct=30,reason='test',risks='test').model_dump()}).status_code==409
    data={'request_id':'nvda-test-buy','context_id':ctx['context_id'],'model':'qwen3:4b','decision':Decision(action='buy',allocation_pct=100,up_pct=50,flat_pct=20,down_pct=30,reason='test',risks='test').model_dump()}
    assert c.post('/api/experiments/us/worker-decision',json=data).status_code==200
    assert c.post('/api/experiments/us/worker-decision',json=data).status_code==200
    state=c.get('/api/experiments/us/state').json()['wallet']
    assert 0<=state['cash']<100000 and state['shares']<1 and len(state['history'])==1
    assert domestic.state()['cash']==other.state()['cash']==100000
    assert domestic.storage.schema!=us.storage.schema!=other.storage.schema
    ctx=c.get('/api/experiments/us/worker-context').json();data.update(request_id='nvda-paused-test',context_id=ctx['context_id'])
    c.put('/api/experiments/us/pause',json={'enabled':True})
    assert c.post('/api/experiments/us/worker-decision',json=data).status_code==409
