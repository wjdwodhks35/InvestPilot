"""Encrypted operator credentials. API responses never contain saved secrets."""
import json
import os
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError
from app.storage import Database


class TossInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    client_id: str = Field(min_length=1, max_length=256, pattern=r'^\S+$')
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

    def load(self):
        with self.database.db() as db:
            row = db.execute('SELECT payload FROM integration_settings WHERE id=1').fetchone()
        if not row: return None
        if not self.cipher: raise ValueError('설정 암호화 키가 필요합니다. Render 환경변수 INVESTPILOT_SETTINGS_KEY를 설정하세요.')
        try: return json.loads(self.cipher.decrypt(row['payload'].encode()))
        except (InvalidToken, ValueError, TypeError):
            raise ValueError('저장된 설정을 복호화할 수 없습니다. 기존 INVESTPILOT_SETTINGS_KEY를 확인하세요.') from None

    def save(self, value):
        if not self.cipher: raise ValueError('설정 암호화 키가 필요합니다. Render 환경변수 INVESTPILOT_SETTINGS_KEY를 설정하세요.')
        payload = self.cipher.encrypt(json.dumps(value).encode()).decode()
        with self.database.db() as db:
            db.execute('INSERT INTO integration_settings(id,payload) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',(payload,))


def apply_config(broker, config):
    broker.client_id=config.get('client_id','')
    broker.client_secret=config.get('client_secret','')
    broker.account=config.get('account_seq','')
    broker.enabled=config.get('stream_enabled',False)
    broker.token=None; broker.expires=0; broker.holdings=None
    broker.connected=False; broker.last_tick=None; broker.error=None


def create_settings_router(store, broker, lock, restart):
    router=APIRouter(prefix='/api/settings',tags=['Settings'])

    def read_saved():
        try: return store.load()
        except ValueError as exc: raise HTTPException(409,str(exc)) from None

    def status():
        error=None
        try: store.load()
        except ValueError as exc: error=str(exc)
        return dict(storage_ready=store.cipher is not None and error is None,
            storage_error=error, client_id_set=bool(broker.client_id),
            client_secret_set=bool(broker.client_secret), account_set=bool(broker.account),
            **broker.status())

    @router.get('/toss')
    async def get_settings():
        async with lock: return status()

    @router.put('/toss')
    async def save_settings(request:Request):
        # Generic validation errors prevent secret input echo in HTTP 422 bodies.
        try:
            if int(request.headers.get('content-length','0'))>8192: raise ValueError()
            raw=await request.body()
            if len(raw)>8192: raise ValueError()
            data=TossInput.model_validate_json(raw)
        except (ValidationError,ValueError): raise HTTPException(400,'입력 형식을 확인하세요. 공백 없는 Client ID와 Client Secret을 사용하세요.') from None
        async with lock:
            saved=read_saved()
            previous=saved if saved is not None else dict(client_id=broker.client_id,client_secret=broker.client_secret,account_seq=broker.account)
            secret=data.client_secret.get_secret_value() if data.client_secret else ''
            if not secret:
                if previous.get('client_id') != data.client_id: raise HTTPException(400,'Client ID를 변경할 때는 Client Secret도 입력하세요.')
                secret=previous.get('client_secret','')
            if not secret or len(secret)>1024 or any(c.isspace() for c in secret): raise HTTPException(400,'유효한 Client Secret을 입력하세요.')
            config=dict(client_id=data.client_id,client_secret=secret,account_seq=(data.account_seq if data.account_seq is not None else previous.get('account_seq','') if previous.get('client_id')==data.client_id else ''),stream_enabled=data.stream_enabled)
            try: store.save(config)
            except ValueError as exc: raise HTTPException(409,str(exc)) from None
            await restart(config)
            return status()

    @router.delete('/toss')
    async def disconnect():
        async with lock:
            read_saved()
            config=dict(client_id='',client_secret='',account_seq='',stream_enabled=False)
            try: store.save(config)
            except ValueError as exc: raise HTTPException(409,str(exc)) from None
            await restart(config)
            return status()

    @router.post('/toss/test')
    async def test_connection():
        async with lock:
            read_saved()
            try:
                await broker.read('/api/v1/accounts')
                return {'ok':True,'message':'인증 및 계좌 조회 성공. 보유종목 조회에는 계좌 식별값이 필요합니다.'}
            except ValueError: raise HTTPException(409,'토스 연결 정보를 먼저 저장하세요.') from None
            except Exception: raise HTTPException(502,'토스 연결 실패. Client ID·Secret과 토스 허용 IP 설정을 확인하세요.') from None
    return router
