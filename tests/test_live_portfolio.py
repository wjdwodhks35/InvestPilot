from datetime import datetime,timezone,timedelta
import asyncio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.engine import Engine
from app.portfolio import breakdown
from app.experiments.ai_paper import Wallet,OllamaExperiment,Snapshot
from app.experiments.ai_api import create_ai_router


def test_live_source_cannot_use_manual_or_old_prices(tmp_path):
    e=Engine(tmp_path/'paper.db');e.quote('005930',50000,0);e.price_source('toss_live')
    with pytest.raises(ValueError):e.order('005930','buy',1,'missing-price')
    with pytest.raises(ValueError):e.quote('005930',1,0)
    e.market_tick('005930',70000,(datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat())
    with pytest.raises(ValueError):e.order('005930','buy',1,'stale-price')
    e.market_tick('005930',71000,datetime.now(timezone.utc).isoformat())
    assert e.order('005930','buy',1,'current-price')['price']==71000
    assert e.snapshot()['cash']==929000
    assert e.snapshot()['positions'][0]['price']==71000
    assert Engine(tmp_path/'paper.db').snapshot()['price_source']=='toss_live'


def test_categories_currency_separation_and_unknown():
    h={'items':[{'symbol':'005930','quantity':'1','lastPrice':'100','currency':'KRW'},
                {'symbol':'UNKNOWN','quantity':'3','lastPrice':'100','currency':'KRW'},
                {'symbol':'AAPL','quantity':'2','lastPrice':'100','currency':'USD'}]}
    b=breakdown(h,{'AAPL':'기술'})
    kr,us=b['currencies']
    assert kr['currency']=='KRW' and kr['categories'][0]['category']=='미분류'
    assert kr['categories'][0]['weight_pct']==75
    assert us['categories'][0]['weight_pct']==100
    assert not breakdown(None,{})['loaded']


def test_remote_ai_revalidates_price_pause_and_idempotency(tmp_path):
    wallet=Wallet(tmp_path/'ai.db');experiment=OllamaExperiment(wallet)
    snap=Snapshot(price=70000,at=datetime.now(timezone.utc).isoformat(),source='toss_live')
    app=FastAPI();app.include_router(create_ai_router(experiment,lambda:snap))
    body={'request_id':'worker-test-123','model':'qwen3:4b','price':70000,'at':snap.at,
          'decision':{'action':'buy','allocation_pct':10,'up_pct':40,'flat_pct':30,'down_pct':30,'reason':'test','risks':'test'}}
    with TestClient(app) as c:
        assert c.post('/api/experiments/ai/worker-decision',json=body).status_code==409
        wallet.pause(False)
        assert c.post('/api/experiments/ai/worker-decision',json={**body,'price':1}).status_code==409
        first=c.post('/api/experiments/ai/worker-decision',json=body)
        assert first.status_code==200
        assert c.post('/api/experiments/ai/worker-decision',json=body).json()==first.json()
        assert len(wallet.state()['history'])==1
        assert c.get('/api/experiments/ai/learning-data').json()['ollama_weights_trained'] is False
