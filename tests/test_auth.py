import pytest
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.auth import AuthSettings, AuthStore, install_auth

PASSWORD='owner-test-password-123'
ORIGIN='http://testserver'


def application(tmp_path, configured=True, secure=False, enabled=True, clock=None):
    store=AuthStore(tmp_path/'auth.db',**({'clock':clock} if clock else {}))
    if configured:store.configure('owner',PASSWORD)
    app=FastAPI()
    @app.get('/')
    def home():return {'private':'dashboard'}
    @app.get('/api/private')
    def private():return {'private':'account'}
    @app.post('/api/private')
    def change():return {'changed':True}
    install_auth(app,store,AuthSettings(enabled=enabled,secure=secure,public_origin=ORIGIN),Path('app/static'))
    return app,store


def login(client, password=PASSWORD, origin=ORIGIN):
    return client.post('/api/auth/login',json={'username':'owner','password':password},headers={'Origin':origin})


def test_every_private_surface_requires_login(tmp_path):
    app,store=application(tmp_path)
    with TestClient(app) as c:
        assert c.get('/',follow_redirects=False).status_code==303
        for path in ['/api/private','/api/experiments/top50/comparison','/openapi.json']:
            assert c.get(path).status_code==401
        assert c.get('/docs',follow_redirects=False).status_code==303
        assert c.get('/static/index.html',follow_redirects=False).status_code==303
        assert c.get('/login').status_code==200
        assert c.get('/health').json()=={'status':'ok'}
        assert c.get('/api/auth/session').json()['authenticated'] is False
        assert c.get('/api/private').headers['cache-control']=='no-store'


def test_login_logout_revocation_and_session_rotation(tmp_path):
    app,store=application(tmp_path)
    with TestClient(app) as c:
        r=login(c);assert r.status_code==200
        cookie=r.headers['set-cookie'];assert 'HttpOnly' in cookie and 'SameSite=strict' in cookie
        old=c.cookies.get('investpilot_session')
        assert c.get('/api/private').status_code==200
        assert c.get('/api/auth/session').json()['username']=='owner'
        assert login(c).status_code==200
        assert store.authenticate(old) is None
        token=c.cookies.get('investpilot_session')
        assert c.post('/api/auth/logout',headers={'Origin':ORIGIN}).status_code==200
        assert store.authenticate(token) is None
        assert c.get('/api/private').status_code==401


def test_secure_cookie_and_no_plain_password_or_token_storage(tmp_path):
    app,store=application(tmp_path,secure=True)
    with TestClient(app,base_url='https://testserver') as c:
        r=login(c);assert r.status_code==200
        assert '__Host-investpilot_session=' in r.headers['set-cookie'] and '; Secure' in r.headers['set-cookie']
        token=c.cookies.get('__Host-investpilot_session')
        assert c.get('/api/private').status_code==200
    raw=Path(store.path).read_bytes()
    assert PASSWORD.encode() not in raw and token.encode() not in raw


def test_csrf_on_login_logout_and_mutations(tmp_path):
    app,store=application(tmp_path)
    with TestClient(app) as c:
        assert login(c,origin='https://attacker.example').status_code==403
        assert login(c).status_code==200
        assert c.post('/api/private').status_code==403
        assert c.post('/api/auth/logout',headers={'Origin':'null'}).status_code==403
        assert c.post('/api/private',headers={'Origin':ORIGIN}).status_code==200


def test_throttling_expiry_and_password_reset(tmp_path):
    now=[1000.0]
    app,store=application(tmp_path,clock=lambda:now[0])
    with TestClient(app) as c:
        for _ in range(5):assert login(c,password='wrong').status_code==401
        assert login(c).status_code==429
        now[0]+=901
        assert login(c).status_code==200
        now[0]+=8*3600
        assert c.get('/api/private').status_code==401
        assert login(c).status_code==200
        store.configure('owner','changed-password-123',replace=True)
        assert c.get('/api/private').status_code==401
        assert login(c).status_code==401


def test_unconfigured_fail_closed_and_local_only_bypass(tmp_path):
    app,store=application(tmp_path,configured=False)
    with TestClient(app) as c:
        assert login(c).status_code==503
        assert c.get('/api/private').status_code==401
    app,store=application(tmp_path,configured=False,enabled=False)
    with TestClient(app) as c:
        assert c.get('/api/private').status_code==200
    with TestClient(app,base_url='http://public.example') as c:
        assert c.get('/api/private').status_code==403


def test_invalid_settings_and_weak_password_rejected(tmp_path,monkeypatch):
    store=AuthStore(tmp_path/'auth.db')
    with pytest.raises(ValueError):store.configure('owner','short')
    monkeypatch.setenv('INVESTPILOT_PUBLIC_ORIGIN','https://site.example/path')
    with pytest.raises(ValueError):AuthSettings.environment()


def test_oversized_login_is_rejected_before_password_processing(tmp_path):
    app,store=application(tmp_path)
    with TestClient(app) as c:
        r=c.post('/api/auth/login',content=b'x'*9000,headers={'Origin':ORIGIN,'Content-Type':'application/json'})
        assert r.status_code==413
        assert login(c).status_code==200


def test_sessions_survive_restart_and_tampered_tokens_do_not_authenticate(tmp_path):
    app,store=application(tmp_path)
    token=store.login('owner',PASSWORD,'127.0.0.1',3600)
    reopened=AuthStore(tmp_path/'auth.db')
    assert reopened.authenticate(token)=='owner'
    assert reopened.authenticate(token+'changed') is None
    with pytest.raises(ValueError):store.configure('owner',PASSWORD)


def test_external_configuration_requires_https_and_secure_cookies(monkeypatch):
    monkeypatch.setenv('INVESTPILOT_PUBLIC_ORIGIN','http://public.example')
    with pytest.raises(ValueError):AuthSettings.environment()
    monkeypatch.setenv('INVESTPILOT_PUBLIC_ORIGIN','https://public.example')
    monkeypatch.setenv('INVESTPILOT_AUTH_SECURE_COOKIE','false')
    with pytest.raises(ValueError):AuthSettings.environment()
