"""Single-owner authentication with durable, revocable server-side sessions."""
import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.requests import HTTPConnection


@dataclass(frozen=True)
class AuthSettings:
    enabled: bool = True
    secure: bool = True
    public_origin: str = ''
    session_seconds: int = 8 * 3600

    @classmethod
    def environment(cls):
        def flag(key, default):
            value = os.getenv(key, default).lower()
            if value not in ('true', 'false'): raise ValueError(key+' must be true or false')
            return value == 'true'
        origin = os.getenv('INVESTPILOT_PUBLIC_ORIGIN', '').rstrip('/')
        secure = flag('INVESTPILOT_AUTH_SECURE_COOKIE', 'true')
        if origin:
            parts = urlsplit(origin)
            if parts.scheme not in ('http', 'https') or not parts.netloc or parts.path or parts.query or parts.fragment or parts.username:
                raise ValueError('INVESTPILOT_PUBLIC_ORIGIN must contain only scheme and host')
            if parts.hostname not in ('127.0.0.1', 'localhost', '::1') and (parts.scheme != 'https' or not secure):
                raise ValueError('External deployment requires HTTPS and secure cookies')
        return cls(enabled=flag('INVESTPILOT_AUTH_ENABLED', 'true'),
                   secure=secure, public_origin=origin)

    @property
    def cookie_name(self):
        return '__Host-investpilot_session' if self.secure else 'investpilot_session'


def password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1,
                          dklen=32, maxmem=64*1024*1024).hex()


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


class LoginFailed(Exception): pass
class RateLimited(Exception): pass
class NotConfigured(Exception): pass


class AuthStore:
    def __init__(self, path, clock=time.time):
        self.path = str(path); self.clock = clock
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS owner (id INTEGER PRIMARY KEY CHECK(id=1), username TEXT NOT NULL, salt TEXT NOT NULL, password_hash TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, expires_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS attempts (address_hash TEXT NOT NULL, at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS attempts_at ON attempts(at);
            ''')
        try: os.chmod(self.path, 0o600)
        except OSError: pass

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db: yield db
        finally: db.close()

    def configured(self):
        with self.db() as db: return db.execute('SELECT 1 FROM owner').fetchone() is not None

    def configure(self, username, password, replace=False):
        if not 3 <= len(username) <= 60 or username != username.strip() or any(ord(c)<32 for c in username):
            raise ValueError('계정 이름은 앞뒤 공백 없이 3~60자로 설정하세요.')
        if not 12 <= len(password) <= 256: raise ValueError('비밀번호는 12~256자로 설정하세요.')
        salt = secrets.token_hex(16); hashed = password_hash(password, salt)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM owner').fetchone() and not replace:
                raise ValueError('계정이 이미 있습니다. 변경하려면 --replace를 사용하세요.')
            db.execute('INSERT OR REPLACE INTO owner VALUES (1,?,?,?)', (username, salt, hashed))
            db.execute('DELETE FROM sessions'); db.execute('DELETE FROM attempts')

    def login(self, username, password, address, lifetime, previous_token=''):
        now = self.clock(); address = token_hash(address)
        # A write transaction serializes the limiter and password check across workers.
        failed = False
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM attempts WHERE at <= ?', (now-900,))
            db.execute('DELETE FROM sessions WHERE expires_at <= ?', (now,))
            owner = db.execute('SELECT * FROM owner').fetchone()
            if not owner: raise NotConfigured()
            count = db.execute('SELECT COUNT(*) FROM attempts WHERE address_hash=?', (address,)).fetchone()[0]
            total = db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]
            if count >= 5 or total >= 50: raise RateLimited()
            valid_password = hmac.compare_digest(password_hash(password, owner['salt']), owner['password_hash'])
            valid_name = hmac.compare_digest(username.encode(), owner['username'].encode())
            if not valid_password or not valid_name:
                db.execute('INSERT INTO attempts VALUES (?,?)', (address, now)); failed = True
            else:
                token = secrets.token_urlsafe(32)
                if previous_token: db.execute('DELETE FROM sessions WHERE token_hash=?', (token_hash(previous_token),))
                db.execute('INSERT INTO sessions VALUES (?,?)', (token_hash(token), now+lifetime))
                db.execute('DELETE FROM attempts WHERE address_hash=?', (address,))
        if failed: raise LoginFailed()
        return token

    def authenticate(self, token):
        if not token or len(token)>256: return None
        with self.db() as db:
            row=db.execute('SELECT owner.username FROM sessions CROSS JOIN owner WHERE token_hash=? AND expires_at>?',
                           (token_hash(token), self.clock())).fetchone()
        return row['username'] if row else None

    def revoke(self, token):
        with self.db() as db: db.execute('DELETE FROM sessions WHERE token_hash=?', (token_hash(token),))


def local_connection(request):
    return bool(request.client and request.client.host in ('127.0.0.1', '::1', 'testclient') and
                request.url.hostname in ('127.0.0.1', 'localhost', '::1', 'testserver'))


def same_origin(request, settings):
    expected=settings.public_origin
    if not expected and local_connection(request):
        expected=f'{request.url.scheme}://{request.url.netloc}'
    return bool(expected and request.headers.get('origin') == expected)


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=1, max_length=256)


def install_auth(app, store, settings, static):
    router=APIRouter(prefix='/api/auth', tags=['Authentication'])

    @router.get('/session')
    async def session(request: Request):
        username=await run_in_threadpool(store.authenticate, request.cookies.get(settings.cookie_name,''))
        return {'enabled':settings.enabled,'authenticated':username is not None,'username':username,
                'configured':await run_in_threadpool(store.configured)}

    @router.post('/login')
    async def login(data: LoginInput, request: Request, response: Response):
        if not settings.enabled: raise HTTPException(409, '로그인 보호가 꺼져 있습니다.')
        try:
            token=await run_in_threadpool(store.login, data.username, data.password,
                request.client.host if request.client else 'unknown', settings.session_seconds,
                request.cookies.get(settings.cookie_name,''))
        except NotConfigured as exc: raise HTTPException(503, '서버에서 로그인 계정을 먼저 설정하세요.') from exc
        except LoginFailed as exc: raise HTTPException(401, '계정 이름 또는 비밀번호를 확인하세요.') from exc
        except RateLimited as exc: raise HTTPException(429, '로그인 시도가 많습니다. 15분 후 다시 시도하세요.', headers={'Retry-After':'900'}) from exc
        response.set_cookie(settings.cookie_name,token,max_age=settings.session_seconds,httponly=True,
                            secure=settings.secure,samesite='strict',path='/')
        return {'authenticated':True}

    @router.post('/logout')
    async def logout(request: Request, response: Response):
        await run_in_threadpool(store.revoke, request.cookies.get(settings.cookie_name,''))
        response.delete_cookie(settings.cookie_name,httponly=True,secure=settings.secure,samesite='strict',path='/')
        return {'authenticated':False}

    app.include_router(router)
    @app.get('/login', include_in_schema=False)
    def login_page(): return FileResponse(static/'login.html')
    @app.get('/health', include_in_schema=False)
    def health(): return {'status':'ok'}
    app.add_middleware(AuthMiddleware,store=store,settings=settings)


class AuthMiddleware:
    public={'/login','/health','/api/auth/login','/api/auth/session','/static/login.css','/static/login.js'}
    def __init__(self,app,store,settings): self.app=app;self.store=store;self.settings=settings

    async def __call__(self,scope,receive,send):
        if scope['type'] not in ('http','websocket'):
            return await self.app(scope,receive,send)
        request=HTTPConnection(scope);settings=self.settings
        if scope['type']=='websocket':
            username=await run_in_threadpool(self.store.authenticate,request.cookies.get(settings.cookie_name,''))
            if not username or not same_origin(request,settings):
                return await send({'type':'websocket.close','code':1008})
            return await self.app(scope,receive,send)
        async def secure_send(message):
            if message['type']=='http.response.start':
                headers=[(k,v) for k,v in message.get('headers',[]) if k.lower()!=b'cache-control']
                headers.extend([(b'cache-control',b'no-store'),(b'x-content-type-options',b'nosniff'),
                                (b'x-frame-options',b'DENY'),(b'referrer-policy',b'same-origin')])
                message={**message,'headers':headers}
            await send(message)
        if not settings.enabled:
            if not local_connection(request):
                return await JSONResponse({'detail':'로컬 테스트 모드에서는 외부 접속을 허용하지 않습니다.'},403)(scope,receive,secure_send)
            return await self.app(scope,receive,secure_send)
        path=scope['path'];method=scope['method']
        if path not in self.public:
            username=await run_in_threadpool(self.store.authenticate,request.cookies.get(settings.cookie_name,''))
            if not username:
                if path.startswith('/api/') or path=='/openapi.json' or method not in ('GET','HEAD'):
                    response=JSONResponse({'detail':'로그인이 필요합니다.'},401)
                else:
                    # Fixed relative path only; query strings are not copied to redirects.
                    response=RedirectResponse('/login?'+urlencode({'next':path}),status_code=303)
                return await response(scope,receive,secure_send)
            scope.setdefault('state',{})['username']=username
        if method not in ('GET','HEAD','OPTIONS') and not same_origin(request,settings):
            return await JSONResponse({'detail':'요청 출처를 확인할 수 없습니다.'},403)(scope,receive,secure_send)
        if path == '/api/auth/login' and method == 'POST':
            original_receive = receive
            chunks = []; size = 0
            while True:
                message = await original_receive()
                if message['type'] == 'http.disconnect': return
                size += len(message.get('body', b''))
                if size > 8192:
                    return await JSONResponse({'detail':'로그인 요청이 너무 큽니다.'},413)(scope,original_receive,secure_send)
                chunks.append(message)
                if not message.get('more_body', False): break
            async def replay_receive():
                if chunks: return chunks.pop(0)
                return await original_receive()
            receive = replay_receive
        return await self.app(scope,receive,secure_send)
