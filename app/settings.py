"""Encrypted operator credentials. API responses never contain saved secrets."""
import ipaddress
import time
import json
import os
import asyncio
import httpx
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError
from app.storage import Database


class TossInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    client_id: str | None = Field(default=None, min_length=1, max_length=256, pattern=r'^\S+$')
    client_secret: SecretStr | None = None
    account_seq: str | None = Field(default=None, max_length=128, pattern=r'^\S*$')
    stream_enabled: bool = False


class SettingsStore:
    def __init__(self, path=None, key=None, database_url=None):
        self.database = Database(path or Path(os.getenv('INVESTPILOT_DATA_DIR','data'))/'settings.db', 'settings', database_url)
        self.cipher = None
        try:
            raw = key if key is not None else os.getenv('INVESTPILOT_SETTINGS_KEY','')
            if raw: self.cipher = Fernet(raw.encode() if isinstance(raw,str) else raw)
        except (ValueError, TypeError): pass
        with self.database.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS integration_settings (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS account_integration_settings (user_id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            legacy=db.execute('SELECT payload FROM integration_settings WHERE id=1').fetchone()
            if legacy:
                db.execute('INSERT INTO account_integration_settings VALUES(?,?) ON CONFLICT(user_id) DO NOTHING',('owner',legacy['payload']))
                db.execute('DELETE FROM integration_settings WHERE id=1')

    def load(self, user_id="owner"):
        with self.database.db() as db:
            row = db.execute('SELECT payload FROM account_integration_settings WHERE user_id=?',(user_id,)).fetchone()
        if not row: return None
        if not self.cipher: raise ValueError('설정 암호화 키가 필요합니다. Render 환경변수 INVESTPILOT_SETTINGS_KEY를 설정하세요.')
        try: return json.loads(self.cipher.decrypt(row['payload'].encode()))
        except (InvalidToken, ValueError, TypeError):
            raise ValueError('저장된 설정을 복호화할 수 없습니다. 기존 INVESTPILOT_SETTINGS_KEY를 확인하세요.') from None

    def save(self, value, user_id="owner"):
        if not self.cipher: raise ValueError('설정 암호화 키가 필요합니다. Render 환경변수 INVESTPILOT_SETTINGS_KEY를 설정하세요.')
        payload = self.cipher.encrypt(json.dumps(value).encode()).decode()
        with self.database.db() as db:
            db.execute('INSERT INTO account_integration_settings(user_id,payload) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET payload=excluded.payload',(user_id,payload))


def apply_config(broker, config):
    broker.client_id=config.get('client_id','')
    broker.client_secret=config.get('client_secret','')
    broker.account=config.get('account_seq','')
    broker.enabled=config.get('stream_enabled',False)
    broker.token=None; broker.expires=0; broker.holdings=None
    broker.connected=False; broker.last_tick=None; broker.error=None


def connection_error(exc):
    if isinstance(exc,httpx.HTTPStatusError):
        status=exc.response.status_code
        if status==401: return '토스 인증 실패(401). 발급한 Client ID·Client Secret과 키 활성 상태를 확인하세요.'
        if status==403: return '토스 접근 거부(403). 토스 Open API 허용 IP에 Render 서버의 Outbound IP를 등록하고 API 권한을 확인하세요. 휴대폰 IP가 아닙니다.'
        if status==429: return '토스 호출 한도 초과(429). 잠시 후 다시 테스트하세요.'
        return f'토스 서버 응답 오류({status}). 잠시 후 다시 테스트하세요.'
    if isinstance(exc,httpx.TimeoutException): return '토스 서버 응답 시간이 초과됐습니다. 잠시 후 다시 테스트하세요.'
    if isinstance(exc,httpx.ConnectError): return '서버에서 토스 API에 접속할 수 없습니다. 서버 네트워크 연결을 확인하세요.'
    if isinstance(exc,ValueError): return '토스 연결 정보를 먼저 저장하세요.'
    return '토스 응답을 처리하지 못했습니다. 잠시 후 다시 테스트하세요.'


class BrokerAccounts:
    def __init__(self,store,owner_broker):
        self.store=store;self.owner_broker=owner_broker;self.items={};self.last_tests={};self.engine_for=lambda uid:owner_broker.engine

    def get(self,user_id):
        if user_id not in self.items:
            from app.broker import TossBroker
            broker=self.owner_broker if user_id=='owner' else TossBroker(self.engine_for(user_id))
            try:
                config=self.store.load(user_id)
                if config is not None: apply_config(broker,config)
                elif user_id!='owner': apply_config(broker,{})
            except ValueError: apply_config(broker,{})
            self.items[user_id]=dict(broker=broker,lock=asyncio.Lock(),task=None)
        return self.items[user_id]

    async def restart(self,user_id,config):
        item=self.get(user_id)
        if item['task']:
            item['task'].cancel()
            try: await item['task']
            except asyncio.CancelledError: pass
        apply_config(item['broker'],config)
        self.last_tests.pop(user_id,None)
        item['task']=asyncio.create_task(item['broker'].loop()) if config.get('stream_enabled') and item['broker'].status()['configured'] else None

    async def start(self):
        with self.store.database.db() as db:
            ids=[row['user_id'] for row in db.execute('SELECT user_id FROM account_integration_settings')]
        for user_id in set(ids+['owner']):
            item=self.get(user_id);b=item['broker']
            if b.enabled and b.status()['configured']:
                item['task']=asyncio.create_task(b.loop())

    async def stop(self):
        for item in self.items.values():
            if item['task']: item['task'].cancel()
        for item in self.items.values():
            if item['task']:
                try: await item['task']
                except asyncio.CancelledError: pass


def request_user(request):
    # Identity comes from authenticated middleware, never form/query input.
    return getattr(request.state,'user_id',None) or 'owner'


def create_settings_router(store, broker, lock, restart, manager=None):
    router=APIRouter(prefix='/api/settings',tags=['Settings'])

    ip_cache={}
    ip_lock=asyncio.Lock()

    @router.get('/outbound-ip')
    async def outbound_ip():
        # Fixed public endpoint only; no user URL or brokerage credentials are sent.
        async with ip_lock:
            if ip_cache and time.monotonic()-ip_cache['at']<60:
                return ip_cache['result']
            try:
                async with httpx.AsyncClient(timeout=8,follow_redirects=False,trust_env=False) as client:
                    response=await client.get('https://api4.ipify.org',headers={'Accept':'text/plain'})
                    response.raise_for_status()
                    value=response.text.strip()
                    if len(value)>15: raise ValueError()
                    address=ipaddress.IPv4Address(value)
                    if not address.is_global: raise ValueError()
                result={'ip':str(address),'checked_at':int(time.time()),'fixed':False}
                ip_cache.update(at=time.monotonic(),result=result)
                return result
            except (httpx.HTTPError,ValueError):
                raise HTTPException(502,'서버 발신 IP를 확인하지 못했습니다. 잠시 후 다시 시도하세요.') from None

    def context(request):
        if manager:
            item=manager.get(request_user(request))
            return item['broker'],item['lock']
        return broker,lock

    def read_saved(request):
        try: return store.load(request_user(request))
        except ValueError as exc: raise HTTPException(409,str(exc)) from None

    async def restart_for(request,config):
        if manager: await manager.restart(request_user(request),config)
        else: await restart(config)

    def status(request,b):
        error=None
        saved=None
        try: saved=store.load(request_user(request))
        except ValueError as exc: error=str(exc)
        source='saved_account' if saved is not None else 'environment' if request_user(request)=='owner' and b.status()['configured'] and error is None else 'unconfigured'
        return dict(config_source=source,storage_ready=store.cipher is not None and error is None,
            storage_error=error, client_id_set=bool(b.client_id),
            client_secret_set=bool(b.client_secret), account_set=bool(b.account),
            **b.status())

    @router.get('/toss')
    async def get_settings(request:Request):
        b,l=context(request)
        async with l: return status(request,b)

    @router.put('/toss')
    async def save_settings(request:Request):
        try:
            if int(request.headers.get('content-length','0'))>8192: raise ValueError()
            raw=await request.body()
            if len(raw)>8192: raise ValueError()
            data=TossInput.model_validate_json(raw)
        except (ValidationError,ValueError): raise HTTPException(400,'입력 형식을 확인하세요. 공백 없는 Client ID와 Client Secret을 사용하세요.') from None
        b,l=context(request)
        async with l:
            saved=read_saved(request)
            previous=saved if saved is not None else dict(client_id=b.client_id,client_secret=b.client_secret,account_seq=b.account)
            client_id=data.client_id or previous.get('client_id','')
            secret=data.client_secret.get_secret_value() if data.client_secret else ''
            if not secret:
                if previous.get('client_id') != client_id: raise HTTPException(400,'Client ID를 변경할 때는 Client Secret도 입력하세요.')
                secret=previous.get('client_secret','')
            if not client_id or not secret or len(secret)>1024 or any(c.isspace() for c in secret): raise HTTPException(400,'유효한 Client ID·Client Secret을 입력하세요.')
            config=dict(client_id=client_id,client_secret=secret,account_seq=(data.account_seq if data.account_seq is not None else previous.get('account_seq','') if previous.get('client_id')==client_id else ''),stream_enabled=data.stream_enabled)
            try: store.save(config,request_user(request))
            except ValueError as exc: raise HTTPException(409,str(exc)) from None
            await restart_for(request,config)
            return status(request,b)

    @router.delete('/toss')
    async def disconnect(request:Request):
        b,l=context(request)
        async with l:
            read_saved(request)
            config=dict(client_id='',client_secret='',account_seq='',stream_enabled=False)
            try: store.save(config,request_user(request))
            except ValueError as exc: raise HTTPException(409,str(exc)) from None
            await restart_for(request,config)
            return status(request,b)

    @router.post('/toss/test')
    async def test_connection(request:Request):
        b,l=context(request)
        async with l:
            read_saved(request)
            try:
                await b.read('/api/v1/accounts')
                return {'ok':True,'message':'인증 및 계좌 조회 성공. 계좌 불러오기를 눌러 계좌를 선택하세요.'}
            except Exception as exc: raise HTTPException(502 if not isinstance(exc,ValueError) else 409,connection_error(exc)) from None
    return router
