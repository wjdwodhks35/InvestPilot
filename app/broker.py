"""Read-only Toss adapter, based on official OpenAPI/AsyncAPI specs.
Real holdings and market ticks never alter paper cash or trigger paper orders.
"""
import asyncio
import json
import os
import time
from datetime import datetime, timezone
from decimal import Decimal

import httpx
from websockets.asyncio.client import connect
from app.engine import WATCHLIST

class TossBroker:
    def __init__(self, engine):
        self.engine=engine
        self.client_id=os.getenv('TOSS_CLIENT_ID','')
        self.client_secret=os.getenv('TOSS_CLIENT_SECRET','')
        self.account=os.getenv('TOSS_ACCOUNT_SEQ','')
        self.enabled=os.getenv('TOSS_STREAM_ENABLED','false').lower()=='true'
        self.token=None;self.expires=0
        self.token_lock=asyncio.Lock()
        self.connected=False;self.last_tick=None;self.error=None
        self.holdings=None

    def status(self):
        return dict(configured=bool(self.client_id and self.client_secret),
            stream_enabled=self.enabled,connected=self.connected,last_tick=self.last_tick,
            error=self.error,holdings_loaded=self.holdings is not None,real_orders_enabled=False)

    async def access_token(self, client):
        async with self.token_lock:
            if self.token and time.monotonic()<self.expires: return self.token
            if not self.client_id or not self.client_secret: raise ValueError('토스 인증정보가 미설정입니다')
            r=await client.post('https://openapi.tossinvest.com/oauth2/token',data={
                'grant_type':'client_credentials','client_id':self.client_id,'client_secret':self.client_secret})
            r.raise_for_status();d=r.json()
            self.token=d['access_token'];self.expires=time.monotonic()+max(0,int(d['expires_in'])-60)
            return self.token

    async def read(self,path,account=False,client=None,params=None):
        if path not in ['/api/v1/accounts','/api/v1/holdings','/api/v1/prices']:raise ValueError('읽기 허용 경로가 아닙니다')
        async def call(c):
            headers={'Authorization':'Bearer '+await self.access_token(c)}
            if account:
                if not self.account: raise ValueError('TOSS_ACCOUNT_SEQ가 미설정입니다')
                headers['X-Tossinvest-Account']=self.account
            r=await c.get('https://openapi.tossinvest.com'+path,headers=headers,params=params)
            if r.status_code==401:self.token=None;self.expires=0
            r.raise_for_status();return r.json()['result']
        if client:return await call(client)
        async with httpx.AsyncClient(timeout=15,trust_env=False) as c:return await call(c)

    def consume(self,frame):
        if frame.get('type')=='subscriptions':
            if frame.get('rejected'): self.error='일부 시세 구독이 거부되었습니다'
            return
        if frame.get('type')=='error': raise ValueError('웹소켓 서버 오류')
        if frame.get('type')!='message': return
        parts=frame.get('topic','').split(':')
        if len(parts)!=3 or parts[:2]!=['trade','kr']:return
        symbol=parts[2]
        if symbol not in {s for s,n,t in WATCHLIST}:return
        d=frame['data']
        if d['currency']!='KRW':return
        price=Decimal(d['price']);stamp=datetime.fromisoformat(d['timestamp'].replace('Z','+00:00'))
        if not price.is_finite() or price<=0 or price!=price.to_integral_value() or not stamp.tzinfo:return
        age=(datetime.now(timezone.utc)-stamp).total_seconds()
        if age>60 or age< -5:return
        # Preserve exchange timestamps. Old/replayed ticks cannot refresh quote freshness.
        self.engine.market_tick(symbol,int(price),stamp.astimezone(timezone.utc).isoformat())
        self.last_tick=stamp.isoformat()

    async def keepalive(self,ws):
        while True:
            await asyncio.sleep(60);await ws.send('PING')

    async def loop(self):
        delay=1
        while True:
            try:
                async with httpx.AsyncClient(timeout=15,trust_env=False) as c:token=await self.access_token(c)
                async with connect('wss://openapi-ws.tossinvest.com/ws/v1',
                    additional_headers={'Authorization':'Bearer '+token},open_timeout=15,
                    ping_interval=20,max_size=1_000_000,proxy=None) as ws:
                    self.connected=True;self.error=None
                    await ws.send(json.dumps([{'type':'trade:kr','codes':[s for s,n,t in WATCHLIST]}]))
                    heartbeat=asyncio.create_task(self.keepalive(ws))
                    try:
                        async for raw in ws:
                            self.consume(json.loads(raw));delay=1
                    finally:
                        heartbeat.cancel()
                        try:await heartbeat
                        except asyncio.CancelledError:pass
            except asyncio.CancelledError:raise
            except Exception as exc:
                self.error=type(exc).__name__+' — 인증정보·허용 IP·연결 상태를 확인하세요'
                if '401' in str(exc):self.token=None;self.expires=0
            finally:self.connected=False
            await asyncio.sleep(delay);delay=min(delay*2,60)
