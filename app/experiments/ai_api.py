"""AI paper experiment API, separated from production and baseline models."""
import csv
import math
import statistics
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from app.experiments.ai_paper import Snapshot


PRICE_ROOT=Path('data/experiments/samsung-price-v1')
PEERS={'000660':'SK하이닉스','000990':'DB하이텍','042700':'한미반도체'}

def technical_context(at,path=None):
    path=Path(path) if path else PRICE_ROOT/'prices.csv'
    if not path.exists():return {'available':False,'note':'가격 이력 없음'}
    stamp=datetime.fromisoformat(at.replace('Z','+00:00')).astimezone(ZoneInfo('Asia/Seoul'))
    rows=[]
    with path.open() as f:
        for r in csv.DictReader(f):
            end=datetime.fromisoformat(r['date']+'T15:30:00+09:00')
            if end<=stamp:rows.append(r)
    if len(rows)<21:return {'available':False,'note':'완료된 일봉 21개 미만'}
    c=[float(r['close']) for r in rows[-21:]];v=[int(r['volume']) for r in rows[-20:]]
    returns=[c[i]/c[i-1]-1 for i in range(1,len(c))]
    return {'available':True,'as_of':rows[-1]['date'],'return_1_pct':returns[-1]*100,
        'return_5_pct':(c[-1]/c[-6]-1)*100,'ma5':statistics.mean(c[-5:]),'ma20':statistics.mean(c[-20:]),
        'volatility_20_pct':statistics.stdev(returns)*100,'volume_ratio':v[-1]/statistics.mean(v) if sum(v) else None,
        'note':'완료된 일봉만 사용. 현재 체결가격과 이력 기준일은 다를 수 있습니다.'}

def market_context(at):
    base=technical_context(at)
    peers=[]
    for symbol,name in PEERS.items():
        values=technical_context(at,PRICE_ROOT/f'peer_{symbol}.csv')
        peers.append({'symbol':symbol,'name':name,**values})
    return {'target':base,'related_stocks':peers,
            'note':'국내 반도체 비교 종목입니다. 상대 종목 상승이 삼성전자 상승을 보장하지 않습니다. 지수·미국 종목은 아직 미포함.'}

class Step(BaseModel):
    request_id: str = Field(min_length=8,max_length=100)
    price: int | None = Field(default=None,gt=0,le=100000000)
class Control(BaseModel):
    enabled: bool
class Reset(BaseModel):
    initial_amount: int = Field(default=100000,ge=1000,le=10000000)


def create_ai_router(experiment,provider,news_provider=lambda:[]):
    router=APIRouter(prefix='/api/experiments/ai',tags=['Ollama paper experiment'])
    @router.get('/state')
    def state():
        quote=provider()
        wallet=experiment.wallet.state(quote.price if quote else None)
        valuation_at=quote.at if quote else None
        valuation_source='toss_live' if quote else 'unavailable'
        if wallet['equity'] is None and wallet['history']:
            valuation_at=wallet['history'][0]['at']
            valuation_source='last_decision_price'
            wallet=experiment.wallet.state(wallet['history'][0]['price'])
        return {'wallet':wallet,'model':experiment.model,'automatic':experiment.automatic,
                'last_error':experiment.last_error,'has_fresh_live_quote':quote is not None,
                'valuation_at':valuation_at,'valuation_source':valuation_source,
                'probability_status':'LLM 주관적 추정 · 미보정 · 로지스틱 모델 확률과 별개'}
    @router.get('/context')
    def context():return market_context(datetime.now(ZoneInfo('Asia/Seoul')).isoformat())
    @router.get('/connection')
    async def connection():return await experiment.connection()
    @router.post('/step')
    async def step(data:Step):
        if data.price:
            snapshot=Snapshot(price=data.price,at=datetime.now(ZoneInfo('Asia/Seoul')).isoformat(),source='manual_test',news=news_provider()[:20])
            # Unknown/future publication timestamps are excluded by the adapter.
            snapshot.indicators=market_context(snapshot.at)
        else:
            snapshot=provider()
            if not snapshot:raise HTTPException(409,'삼성전자 최신 토스 체결이 없습니다. 테스트 가격을 입력하세요.')
        try:return await experiment.step(data.request_id,snapshot)
        except ValueError as exc:raise HTTPException(409,str(exc)) from exc
        except Exception as exc:raise HTTPException(502,'Ollama 호출/응답 검증 실패. 가상 주문은 실행하지 않았습니다.') from exc
    @router.put('/automatic')
    async def automatic(data:Control):
        if data.enabled:
            status=await experiment.connection()
            if not status['connected'] or not status['installed']:raise HTTPException(409,'로컬 Ollama와 설정한 모델 설치를 먼저 확인하세요')
            if not provider():raise HTTPException(409,'자동 테스트에는 60초 이내 삼성전자 토스 체결이 필요합니다')
        experiment.automatic=data.enabled
        experiment.wallet.pause(not data.enabled)
        return {'automatic':experiment.automatic,'mode':'paper_only'}
    @router.put('/pause')
    def pause(data:Control):
        experiment.wallet.pause(data.enabled)
        if data.enabled:experiment.automatic=False
        return {'paused':data.enabled}
    @router.post('/reset')
    async def reset(data:Reset):
        experiment.automatic=False
        async with experiment.lock:experiment.wallet.reset(data.initial_amount)
        return {'wallet':experiment.wallet.state(),'automatic':False}
    return router
