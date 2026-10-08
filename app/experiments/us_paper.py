"""Fixed NVDA paper experiment: read-only broker access and isolated KRW wallet."""
import json
import uuid
from datetime import datetime,timezone
from decimal import Decimal,ROUND_CEILING,InvalidOperation
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,Field
from app.experiments.ai_paper import Snapshot,Decision

PEERS={'AMD':'AMD','AVGO':'브로드컴','MSFT':'마이크로소프트'}

def us_snapshot(prices,fx):
    now=datetime.now(timezone.utc)
    start=datetime.fromisoformat(fx['validFrom'].replace('Z','+00:00'))
    end=datetime.fromisoformat(fx['validUntil'].replace('Z','+00:00'))
    rate=Decimal(fx['rate'])
    if fx['baseCurrency']!='USD' or fx['quoteCurrency']!='KRW' or not start.tzinfo or not end.tzinfo or not start<=now<end or not rate.is_finite() or rate<=0:
        raise ValueError('유효한 USD/KRW 참고 환율이 없습니다')
    target=next((p for p in prices if p.get('symbol')=='NVDA' and p.get('currency')=='USD'),None)
    if not target:raise ValueError('엔비디아 달러 시세가 없습니다')
    usd=Decimal(target['lastPrice'])
    if not usd.is_finite() or usd<=0:raise ValueError('엔비디아 가격 형식 오류')
    peers=[]
    for symbol,name in PEERS.items():
        quote=next((p for p in prices if p.get('symbol')==symbol and p.get('currency')=='USD'),None)
        if quote:
            try:
                stamp=datetime.fromisoformat(quote['timestamp'].replace('Z','+00:00'))
                value=Decimal(quote['lastPrice'])
                if stamp.tzinfo and -5<=(now-stamp).total_seconds()<=60 and value.is_finite() and value>0:
                    peers.append({'symbol':symbol,'name':name,'price_usd':str(value),'at':quote['timestamp']})
            except (KeyError,ValueError,TypeError,InvalidOperation):pass
    snapshot=Snapshot(symbol='NVDA',price=int((usd*rate).to_integral_value(rounding=ROUND_CEILING)),at=target['timestamp'],source='toss_live')
    snapshot.indicators={'target':{'available':False,'note':'과거 가격 이력 미수집'},'price_usd':str(usd),'usd_krw':str(rate),'fx_valid_until':fx['validUntil'],'related_quotes':peers,'note':'미국 주식 원화 환산 모의투자. 현재 시세만 제공; 과거 가격·미국 뉴스 미수집. 참고 환율은 실제 환전 환율과 다릅니다.'}
    return snapshot

class Control(BaseModel):
    enabled:bool
class External(BaseModel):
    request_id:str=Field(min_length=8,max_length=100)
    context_id:str=Field(min_length=32,max_length=32,pattern='^[0-9a-f]+$')
    model:str=Field(min_length=1,max_length=100,pattern=r'^[A-Za-z0-9_.:/-]+$')
    decision:Decision


def create_us_router(wallet_for,market_for):
    router=APIRouter(prefix='/api/experiments/us',tags=['US paper experiment'])
    def prepare(wallet):
        with wallet.db() as c:
            c.execute('CREATE TABLE IF NOT EXISTS worker_context(id TEXT PRIMARY KEY,payload TEXT)')
    @router.get('/state')
    def state():
        w=wallet_for();prepare(w);state=w.state();last=state['history'][0] if state['history'] else None
        if last:state=w.state(last['price'])
        return {'symbol':'NVDA','name':'엔비디아','currency':'KRW','wallet':state,'valuation':'최근 판단 당시 원화 환산 가격' if last else '평가가격 없음','ollama_weights_trained':False}
    @router.put('/pause')
    def pause(data:Control):
        wallet_for().pause(data.enabled);return {'paused':data.enabled}
    @router.get('/worker-context')
    async def context():
        w=wallet_for();prepare(w)
        if w.state()['paused']:raise HTTPException(409,'미국 모의투자를 먼저 준비하기로 허용하세요')
        try:
            prices,fx=await market_for()
            snapshot=us_snapshot(prices,fx)
        except (ValueError,KeyError,TypeError,InvalidOperation):raise HTTPException(409,'60초 이내 엔비디아 시세와 유효한 USD/KRW 환율이 필요합니다') from None
        key=uuid.uuid4().hex
        with w.db() as c:
            c.execute('DELETE FROM worker_context')
            c.execute('INSERT INTO worker_context VALUES (?,?)',(key,snapshot.model_dump_json()))
        return {'context_id':key,'snapshot':snapshot.model_dump(),'wallet':w.state(snapshot.price)}
    @router.post('/worker-decision')
    def decision(data:External):
        w=wallet_for();prepare(w)
        old=w.existing(data.request_id)
        if old:return old
        with w.db() as c:row=c.execute('SELECT payload FROM worker_context WHERE id=?',(data.context_id,)).fetchone()
        if not row:raise HTTPException(409,'판단 자료가 변경됐습니다. 다시 실행하세요')
        try:
            snapshot=Snapshot.model_validate_json(row['payload'])
            end=datetime.fromisoformat(snapshot.indicators['fx_valid_until'].replace('Z','+00:00'))
            if datetime.now(timezone.utc)>=end:raise ValueError('참고 환율 유효기간 만료')
            return w.apply(data.request_id,data.model,snapshot,data.decision)
        except ValueError:raise HTTPException(409,'모의투자 정지 또는 시세·환율 만료. 다시 실행하세요') from None
    return router
