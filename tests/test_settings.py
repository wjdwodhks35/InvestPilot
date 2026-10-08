import asyncio
from pathlib import Path
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.auth import AuthSettings, AuthStore, install_auth
from app.broker import TossBroker
from app.settings import SettingsStore, create_settings_router, apply_config

SECRET='settings-test-only-secret'


def test_encryption_restart_wrong_key_and_no_key(tmp_path):
    key=Fernet.generate_key();path=tmp_path/'settings.db'
    store=SettingsStore(path,key,database_url='')
    config=dict(client_id='test-client',client_secret=SECRET,account_seq='test-account',stream_enabled=False)
    store.save(config)
    assert SECRET.encode() not in path.read_bytes()
    assert b'test-account' not in path.read_bytes()
    assert SettingsStore(path,key,database_url='').load()==config
    with pytest.raises(ValueError,match='복호화'): SettingsStore(path,Fernet.generate_key(),database_url='').load()
    with pytest.raises(ValueError,match='암호화 키'): SettingsStore(path,'',database_url='').save(config)


def test_settings_auth_origin_retention_disconnect_and_no_leaks(tmp_path):
    app=FastAPI();store=SettingsStore(tmp_path/'settings.db',Fernet.generate_key(),database_url='')
    broker=TossBroker(None);apply_config(broker,{})
    async def restart(config): apply_config(broker,config)
    app.include_router(create_settings_router(store,broker,asyncio.Lock(),restart))
    auth=AuthStore(tmp_path/'auth.db',database_url='');auth.configure('admin','test-settings-password-123')
    install_auth(app,auth,AuthSettings(enabled=True,secure=False,public_origin='http://testserver'),Path('app/static'))
    with TestClient(app) as client:
        assert client.get('/api/settings/toss').status_code==401
        origin={'Origin':'http://testserver'}
        assert client.post('/api/auth/login',headers=origin,json={'username':'admin','password':'test-settings-password-123'}).status_code==200
        data=dict(client_id='test-client',client_secret=SECRET,account_seq='test-account',stream_enabled=False)
        assert client.put('/api/settings/toss',json=data).status_code==403
        response=client.put('/api/settings/toss',headers=origin,json=data)
        assert response.status_code==200
        for private in (SECRET,'test-client','test-account'): assert private not in response.text
        data['client_secret']=None;data['account_seq']=None
        assert client.put('/api/settings/toss',headers=origin,json=data).status_code==200
        assert broker.client_secret==SECRET and broker.account=='test-account'
        data['client_id']='changed-client'
        assert client.put('/api/settings/toss',headers=origin,json=data).status_code==400
        response=client.put('/api/settings/toss',headers=origin,json={'client_secret':SECRET,'extra':SECRET})
        assert response.status_code==400 and SECRET not in response.text
        async def failure(*args,**kwargs): raise RuntimeError(SECRET)
        broker.read=failure
        response=client.post('/api/settings/toss/test',headers=origin)
        assert response.status_code==502 and SECRET not in response.text
        async def success(*args,**kwargs): return [{'accountSeq':'private-account'}]
        broker.read=success
        response=client.post('/api/settings/toss/test',headers=origin)
        assert response.json()['ok'] and 'private-account' not in response.text
        assert client.delete('/api/settings/toss',headers=origin).status_code==200
        assert not broker.client_secret and store.load()['client_secret']==''


def test_two_login_accounts_cannot_read_replace_or_disconnect_each_other(tmp_path):
    from app.settings import BrokerAccounts
    app=FastAPI();store=SettingsStore(tmp_path/'settings.db',Fernet.generate_key(),database_url='')
    auth=AuthStore(tmp_path/'auth.db',database_url='');auth.configure('admin','test-admin-password-123')
    auth.add_user('second','test-second-password-123')
    broker=TossBroker(None);apply_config(broker,{})
    manager=BrokerAccounts(store,broker)
    app.include_router(create_settings_router(store,broker,asyncio.Lock(),None,manager))
    install_auth(app,auth,AuthSettings(enabled=True,secure=False,public_origin='http://testserver'),Path('app/static'))
    headers={'Origin':'http://testserver'}
    with TestClient(app) as first,TestClient(app) as second:
        for client,name in [(first,'admin'),(second,'second')]:
            password='test-admin-password-123' if name=='admin' else 'test-second-password-123'
            assert client.post('/api/auth/login',headers=headers,json={'username':name,'password':password}).status_code==200
        assert first.put('/api/settings/toss',headers=headers,json={'client_id':'owner-client','client_secret':'owner-secret','account_seq':'owner-account'}).status_code==200
        assert second.get('/api/settings/toss').json()['configured'] is False
        assert second.get('/api/auth/users').status_code==403
        assert second.post('/api/auth/users',headers=headers,json={'username':'third','password':'third-test-password'}).status_code==403
        assert second.put('/api/settings/toss',headers=headers,json={'client_id':'second-client','client_secret':'second-secret','account_seq':'second-account','user_id':'owner'}).status_code==400
        assert second.put('/api/settings/toss',headers=headers,json={'client_id':'second-client','client_secret':'second-secret','account_seq':'second-account'}).status_code==200
        second_id=auth.user_id('second')
        assert store.load()['client_secret']=='owner-secret'
        assert store.load(second_id)['client_secret']=='second-secret'
        manager.get('owner')['broker'].holdings={'items':[{'name':'owner-private'}]}
        assert manager.get(second_id)['broker'].holdings is None
        assert second.delete('/api/settings/toss',headers=headers).status_code==200
        assert first.get('/api/settings/toss').json()['configured'] is True
        assert first.post('/api/auth/users',headers=headers,json={'username':'third','password':'third-test-password'}).status_code==200
        assert first.get('/api/auth/users').json()[0]['admin'] is True
        token=auth.login('second','test-second-password-123','restart',3600)
        assert AuthStore(tmp_path/'auth.db',database_url='').authenticate(token)=='second'


def test_safe_http_diagnostics():
    import httpx
    from app.settings import connection_error
    for status,label in [(401,'인증 실패'),(403,'접근 거부'),(429,'호출 한도')]:
        response=httpx.Response(status,request=httpx.Request('GET','https://openapi.tossinvest.com/api/v1/accounts'),text=SECRET)
        message=connection_error(httpx.HTTPStatusError(SECRET,request=response.request,response=response))
        assert label in message and SECRET not in message


def test_legacy_encrypted_settings_claimed_only_by_owner(tmp_path):
    key=Fernet.generate_key();store=SettingsStore(tmp_path/'settings.db',key,database_url='')
    value={'client_id':'legacy','client_secret':'legacy-secret'}
    import json
    payload=store.cipher.encrypt(json.dumps(value).encode()).decode()
    with store.database.db() as db: db.execute('INSERT INTO integration_settings VALUES(1,?)',(payload,))
    migrated=SettingsStore(tmp_path/'settings.db',key,database_url='')
    assert migrated.load()==value and migrated.load('different-user') is None
    migrated.save({'client_id':''})
    assert SettingsStore(tmp_path/'settings.db',key,database_url='').load()=={'client_id':''}


def test_account_paper_wallets_rules_and_ai_controls_are_isolated(tmp_path,monkeypatch):
    from app.account_runtime import AccountRuntime,Scoped,current_user
    from app.engine import Engine
    from app.experiments.ai_paper import Wallet,OllamaExperiment
    monkeypatch.setenv('INVESTPILOT_DATA_DIR',str(tmp_path))
    monkeypatch.setenv('INVESTPILOT_DATABASE_URL','')
    engine=Engine(tmp_path/'owner.db');wallet=Wallet(tmp_path/'owner-ai.db')
    runtime=AccountRuntime(engine,wallet,OllamaExperiment(wallet))
    proxy=Scoped(runtime,'engine');ai=Scoped(runtime,'experiment')
    owner_token=current_user.set('owner')
    try:
        proxy.quote('005930',10000,0);proxy.order('005930','buy',2,'owner-paper-order')
        ai.wallet.reset(123456);ai.automatic=True
        account_id='a'*32
        token=current_user.set(account_id)
        try:
            assert proxy.snapshot()['orders']==[] and proxy.snapshot()['cash']==1000000
            assert ai.wallet.state()['cash']==100000 and ai.automatic is False
            proxy.quote('005930',10000,0);proxy.order('005930','buy',1,'second-paper-order')
            ai.wallet.reset(654321)
        finally: current_user.reset(token)
        assert proxy.snapshot()['cash']==980000
        assert len(proxy.snapshot()['orders'])==1
        assert ai.wallet.state()['cash']==123456 and ai.automatic is True
        reopened=AccountRuntime(engine,wallet,OllamaExperiment(wallet))
        assert reopened.get(account_id)['engine'].snapshot()['cash']==990000
        assert reopened.get(account_id)['wallet'].state()['cash']==654321
    finally: current_user.reset(owner_token)


def test_actual_platform_routes_use_authenticated_account_context(tmp_path,monkeypatch):
    from app import main
    from app.account_runtime import AccountRuntime,Scoped
    from app.engine import Engine
    from app.experiments.ai_paper import Wallet,OllamaExperiment
    from app.settings import BrokerAccounts
    monkeypatch.setenv('INVESTPILOT_DATABASE_URL','');monkeypatch.setenv('INVESTPILOT_DATA_DIR',str(tmp_path))
    engine=Engine(tmp_path/'paper.db');wallet=Wallet(tmp_path/'ai.db')
    runtime=AccountRuntime(engine,wallet,OllamaExperiment(wallet))
    monkeypatch.setattr(main,'account_runtime',runtime)
    monkeypatch.setattr(main,'engine',Scoped(runtime,'engine'))
    owner_broker=TossBroker(engine);apply_config(owner_broker,{})
    settings=SettingsStore(tmp_path/'settings.db',Fernet.generate_key(),database_url='')
    manager=BrokerAccounts(settings,owner_broker);manager.engine_for=lambda uid:runtime.get(uid)['engine']
    monkeypatch.setattr(main,'broker_accounts',manager)
    app=FastAPI()
    for route in main.app.router.routes:
        if getattr(route,'path',None) in ('/api/state','/api/quotes','/api/orders','/api/broker/holdings','/api/broker/holdings/refresh','/api/broker/accounts','/api/integrations'):
            app.router.routes.append(route)
    app.middleware('http')(main.account_scope)
    auth=AuthStore(tmp_path/'auth.db',database_url='');auth.configure('admin','platform-admin-password-123');auth.add_user('second','platform-second-password-123')
    install_auth(app,auth,AuthSettings(enabled=True,secure=False,public_origin='http://testserver'),Path('app/static'))
    origin={'Origin':'http://testserver'}
    with TestClient(app) as client:
        def login(name,password):
            assert client.post('/api/auth/login',headers=origin,json={'username':name,'password':password}).status_code==200
        login('admin','platform-admin-password-123')
        client.post('/api/quotes',headers=origin,json={'symbol':'005930','price':10000,'change':0})
        assert client.post('/api/orders',headers=origin,json={'symbol':'005930','side':'buy','qty':2,'request_id':'owner-route-order'}).status_code==200
        manager.get('owner')['broker'].holdings={'items':[{'name':'owner-private'}]}
        login('second','platform-second-password-123')
        assert client.get('/api/state').json()['cash']==1000000
        assert client.get('/api/state').json()['orders']==[]
        assert client.get('/api/broker/holdings').json() is None
        assert client.get('/api/integrations').json()['broker']['configured'] is False
        client.post('/api/quotes',headers=origin,json={'symbol':'005930','price':10000,'change':0})
        client.post('/api/orders',headers=origin,json={'symbol':'005930','side':'buy','qty':1,'request_id':'second-route-order'})
        assert client.get('/api/state').json()['cash']==990000
        login('admin','platform-admin-password-123')
        assert client.get('/api/state').json()['cash']==980000
        assert client.get('/api/broker/holdings').json()['items'][0]['name']=='owner-private'
