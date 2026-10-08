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
