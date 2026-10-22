import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import os
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from app.auth import AuthStore, AuthSettings, install_auth
from app.engine import Engine
from app.portfolio import breakdown, exchange_rate
from app.dividends import DividendScenario, estimate
from app.dividend_market import DividendMarketQuote


def fx():
    now=datetime.now(timezone.utc)
    return dict(baseCurrency='USD',quoteCurrency='KRW',rate='1400',validFrom=(now-timedelta(minutes=1)).isoformat(),validUntil=(now+timedelta(minutes=5)).isoformat())


def holdings():
    return {'items':[dict(symbol='005930',name='삼성전자',currency='KRW',quantity='2',averagePurchasePrice='50000',lastPrice='60000'),
                     dict(symbol='AAPL',name='애플',currency='USD',quantity='3',averagePurchasePrice='100',lastPrice='90')]}


def test_mixed_categories_cost_value_profit_and_fx():
    result=breakdown(holdings(),{'005930':'장기투자','AAPL':'장기투자'},fx())
    krw,usd=result['converted']
    assert Decimal(krw['cost'])==520000 and Decimal(krw['value'])==498000
    assert Decimal(krw['profit'])==-22000
    assert krw['categories'][0]['count']==2
    assert abs(Decimal(usd['profit'])-Decimal(-22000)/1400)<Decimal('1e-24')
    assert result['currencies'][0]['profit']=='20000'
    assert result['currencies'][1]['profit']=='-30'


def test_missing_cost_price_or_fx_does_not_fake_zero():
    h=holdings()
    result=breakdown(h,{})
    assert result['converted'][0]['value'] is None
    assert result['currencies'][0]['value']=='120000'
    del h['items'][0]['averagePurchasePrice']
    result=breakdown(h,{},fx())
    assert result['converted'][0]['cost'] is None and result['converted'][0]['profit'] is None
    h['items'][0]['lastPrice']='NaN'
    assert breakdown(h,{},fx())['converted'][0]['value'] is None
    assert breakdown(None,{})['loaded'] is False


def test_fx_expiry_and_wrong_direction():
    value=fx();value['validUntil']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
    assert exchange_rate(value) is None
    value=fx();value['baseCurrency']='KRW'
    assert exchange_rate(value) is None
    assert exchange_rate({'rate':'Infinity'}) is None


def test_categories_concurrent_and_persistent(tmp_path):
    path=tmp_path/'paper.db'
    first=Engine(path)
    def assign(i):
        Engine(path).assign_categories([f'S{i}'],'분류'+str(i))
    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(assign,range(10)))
    assert len(Engine(path).categories())==10
    assert first.assign_categories(['AAPL','MSFT'],'장기') == Engine(path).categories()


def quote(symbol='AAPL',currency='USD',rate='4',price='300'):
    return DividendMarketQuote(symbol=symbol,provider_symbol=symbol,currency=currency,
        annual_yield_pct=rate,share_price=price,fetched_at=datetime.now(timezone.utc).isoformat())


def test_dividend_market_yield_whole_shares_and_remainder():
    scenario=DividendScenario(symbol='AAPL',investment='1000',currency='USD',assumed_tax_pct='10',payments_per_year=4)
    result=estimate(scenario,quote(),fx());usd=result['converted'][1]
    assert result['shares']=='3' and usd['unspent']=='100'
    assert usd['annual_gross']=='36' and usd['annual_net']=='32.4'
    assert usd['monthly_average_net']=='2.7' and usd['per_payment_net']=='8.1'
    assert result['converted'][0]['annual_gross']=='50400'
    assert estimate(scenario,quote())['converted'][0]['annual_net'] is None


def test_dividend_too_small_zero_yield_and_fractional():
    s=DividendScenario(symbol='AAPL',investment='100',currency='USD')
    assert estimate(s,quote(rate='5'))['shares']=='0'
    s=s.model_copy(update={'fractional':True})
    assert Decimal(estimate(s,quote(rate='5'))['converted'][1]['annual_gross'])==5
    assert estimate(s,quote(rate='0',price=None))['converted'][1]['annual_gross']=='0'
    for change in [{'investment':'NaN'},{'annual_yield_pct':4},{'assumed_tax_pct':101},{'share_price':1}]:
        with pytest.raises(ValidationError):
            DividendScenario(**({'symbol':'AAPL','investment':100,'currency':'USD'}|change))
    with pytest.raises(ValueError):
        estimate(s,quote(currency='KRW'))


@pytest.fixture
def platform(tmp_path,monkeypatch):
    from app import main
    from app.account_runtime import AccountRuntime,Scoped
    from app.experiments.ai_paper import Wallet,OllamaExperiment
    from app.settings import SettingsStore,BrokerAccounts
    from app.broker import TossBroker
    monkeypatch.setenv('INVESTPILOT_DATABASE_URL','')
    monkeypatch.setenv('INVESTPILOT_DATA_DIR',str(tmp_path))
    owner=Engine(tmp_path/'paper.db');wallet=Wallet(tmp_path/'ai.db')
    runtime=AccountRuntime(owner,wallet,OllamaExperiment(wallet))
    manager=BrokerAccounts(SettingsStore(tmp_path/'settings.db',database_url=''),TossBroker(owner))
    manager.engine_for=lambda uid:runtime.get(uid)['engine']
    monkeypatch.setattr(main,'engine',Scoped(runtime,'engine'))
    monkeypatch.setattr(main,'account_runtime',runtime)
    monkeypatch.setattr(main,'broker_accounts',manager)
    async def market_lookup(symbol):
        return quote(symbol=symbol,currency='KRW' if symbol.isdigit() else 'USD',price=None)
    monkeypatch.setattr(main,'dividend_market',SimpleNamespace(lookup=market_lookup))
    store=AuthStore(tmp_path/'auth.db',database_url='')
    store.configure('admin','test-password-12345');store.add_user('other','test-password-12345')
    app=FastAPI()
    for route in main.app.routes:
        if getattr(route,'path','').startswith(('/api/broker/categories','/api/broker/dividends','/api/broker/breakdown','/api/broker/exchange-rate')):
            app.router.routes.append(route)
    app.middleware('http')(main.account_scope)
    install_auth(app,store,AuthSettings(enabled=True,secure=False,public_origin='http://testserver'),Path('app/static'))
    async def read(*args,**kwargs):
        return fx()
    monkeypatch.setattr(manager.owner_broker,'read',read)
    manager.get('owner')['broker'].holdings=holdings()
    yield app,store,runtime,manager


def test_saved_categories_and_dividends_isolated_across_accounts(platform):
    app,auth,runtime,manager=platform
    origin={'Origin':'http://testserver'}
    scenario=dict(symbol='005930',investment='1000000',currency='KRW',assumed_tax_pct='0',payments_per_year=4,fractional=False)
    with TestClient(app) as client:
        assert client.get('/api/broker/dividends/scenario').status_code==401
        def login(user):
            assert client.post('/api/auth/login',headers=origin,json={'username':user,'password':'test-password-12345'}).status_code==200
        login('admin')
        assert client.put('/api/broker/categories/batch',headers=origin,json={'symbols':['005930','AAPL'],'category':'내 장기투자'}).status_code==200
        assert client.post('/api/broker/exchange-rate/refresh',headers=origin).status_code==200
        assert client.get('/api/broker/exchange-rate').json()['latest']['valid'] is True
        assert client.get('/api/broker/breakdown').json()['converted'][0]['profit']=='-22000'
        assert client.put('/api/broker/dividends/scenario',headers=origin,json=scenario).json()['converted'][0]['annual_gross']=='40000'
        assert client.post('/api/broker/dividends/calculate',headers=origin,json={**scenario,'annual_yield_pct':'99'}).status_code==422
        assert client.put('/api/broker/categories/batch',headers=origin,json={'symbols':['AAPL'],'category':'   '}).status_code==400
        login('other')
        assert client.get('/api/broker/breakdown').json()['assignments']=={}
        assert client.get('/api/broker/dividends/scenario').json() is None
        assert client.get('/api/broker/exchange-rate').json()['history']==[]
        assert client.post('/api/broker/dividends/calculate',headers=origin,json=scenario).status_code==200
        assert client.get('/api/broker/dividends/scenario').json() is None  # calculation alone does not save
        login('admin')
        assert client.get('/api/broker/breakdown').json()['assignments']['AAPL']=='내 장기투자'
        assert client.get('/api/broker/dividends/scenario').json()['assumptions']['investment']=='1000000'
        runtime.items['owner']['engine'].dividend_scenario({'investment':'1000','annual_yield_pct':'99'})
        legacy=client.get('/api/broker/dividends/scenario').json()
        assert legacy['status']=='needs_lookup' and legacy['market'] is None and legacy['converted']==[]
    assert Engine(runtime.items['owner']['engine'].path).categories()['AAPL']=='내 장기투자'


def test_postgres_saved_categories_and_dividend_assumptions(tmp_path,monkeypatch):
    url=os.getenv('INVESTPILOT_TEST_POSTGRES_URL')
    if not url:
        pytest.skip('Disposable PostgreSQL required')
    assert urlsplit(url).hostname in ('127.0.0.1','localhost','::1')
    monkeypatch.setenv('INVESTPILOT_DATABASE_URL',url)
    engine=Engine(tmp_path/'unused.db')
    engine.assign_categories(['AAPL'],'배당')
    engine.dividend_scenario({'investment':'1000','currency':'USD'})
    engine.portfolio_fx(fx())
    reopened=Engine(tmp_path/'reopened.db')
    assert reopened.categories()['AAPL']=='배당'
    assert reopened.dividend_scenario()['investment']=='1000'
    assert reopened.portfolio_fx()[-1]['rate']=='1400'
    assert not (tmp_path/'unused.db').exists()


def test_fx_history_persistence_and_bound(tmp_path):
    path=tmp_path/'paper.db'
    engine=Engine(path)
    for n in range(305):
        engine.portfolio_fx({**fx(),'rate':str(1300+n)})
    history=Engine(path).portfolio_fx()
    assert len(history)==300
    assert history[-1]['rate']=='1604'
    assert history[0]['rate']=='1305'
