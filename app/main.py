import os
import asyncio
from contextlib import asynccontextmanager
from dotenv import load_dotenv
load_dotenv()
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from app.engine import Engine
from app.experiments.api import router as experiments_router
from app.experiments.ai_api import create_ai_router
from app.experiments.ai_paper import Wallet, OllamaExperiment, Snapshot

from app.settings import SettingsStore, apply_config, create_settings_router
from app.broker import TossBroker
from app.integrations import NewsService, analyze, news_id

@asynccontextmanager
async def lifespan(app):
    tasks=[asyncio.create_task(ai_experiment.loop(ai_snapshot))]
    if news_service.feeds: tasks.append(asyncio.create_task(news_service.loop()))
    if broker.enabled and broker.status()['configured']: app.state.broker_task=asyncio.create_task(broker.loop())
    try: yield
    finally:
        if getattr(app.state,'broker_task',None): tasks.append(app.state.broker_task)
        for task in tasks: task.cancel()
        for task in tasks:
            try: await task
            except asyncio.CancelledError: pass

app = FastAPI(title='InvestPilot', version='0.2.0', lifespan=lifespan)
app.include_router(experiments_router)
engine = Engine(os.environ.get('INVESTPILOT_DB','data/investpilot.db'))
news_service = NewsService(engine)
broker = TossBroker(engine)
settings_store=SettingsStore()
broker_settings_lock=asyncio.Lock()
try:
    saved_settings=settings_store.load()
    if saved_settings is not None: apply_config(broker,saved_settings)
except ValueError:
    apply_config(broker,{})

async def restart_broker(config):
    task=getattr(app.state,'broker_task',None)
    if task:
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass
    apply_config(broker,config)
    app.state.broker_task=asyncio.create_task(broker.loop()) if broker.enabled and broker.status()['configured'] else None

app.include_router(create_settings_router(settings_store,broker,broker_settings_lock,restart_broker))
ai_wallet=Wallet(os.environ.get('INVESTPILOT_AI_DB','data/ai-paper.db'))
ai_experiment=OllamaExperiment(ai_wallet)

def ai_snapshot():
    quotes=[q for q in engine.market_state() if q['symbol']=='005930']
    if not quotes:return None
    q=quotes[0]
    try:
        snapshot=Snapshot(price=q['price'],at=q['at'],source='toss_live',news=engine.snapshot()['news'][:20])
    except ValueError:return None
    from app.experiments.ai_api import market_context
    snapshot.indicators=market_context(snapshot.at)
    return snapshot

app.include_router(create_ai_router(ai_experiment,ai_snapshot,lambda:engine.snapshot()['news']))
static = Path(__file__).parent/'static'
app.mount('/static', StaticFiles(directory=static), name='static')

class Quote(BaseModel):
    symbol: str = Field(pattern=r'^\d{6}$')
    price: int = Field(gt=0, le=100000000)
    change: float = Field(ge=-100, le=1000)
class Order(BaseModel):
    symbol: str = Field(pattern=r'^\d{6}$')
    side: Literal['buy','sell']
    qty: int = Field(gt=0,le=1000000)
    request_id: str = Field(min_length=8,max_length=100)
class Rules(BaseModel):
    take_profit: float = Field(default=15,gt=0,le=1000)
    stop_loss: float = Field(default=7,gt=0,le=100)
    trailing_stop: float = Field(default=5,gt=0,le=100)
    trailing_activation: float = Field(default=10,gt=0,le=1000)
    max_order: int = Field(default=100000,gt=0,le=10000000)
    daily_buy_limit: int = Field(default=200000,gt=0,le=10000000)
    surge_limit: float = Field(default=15,gt=0,le=100)
    paused: bool = False
class News(BaseModel):
    news_id: str = Field(min_length=8,max_length=200)
    title: str = Field(min_length=1,max_length=500)
    url: str = Field(default='',max_length=2000)
    symbol: str = Field(default='',pattern=r'^(\d{6})?$')

def run(fn,*args):
    try: return fn(*args)
    except ValueError as e: raise HTTPException(409,str(e)) from e
@app.get('/settings')
def settings_page(): return FileResponse(static/'settings.html')

@app.get('/')
def home(): return FileResponse(static/'index.html')
@app.get('/api/state')
def state(): return engine.snapshot()
@app.post('/api/quotes')
def quote(q:Quote): return run(engine.quote,q.symbol,q.price,q.change)
@app.post('/api/orders')
def order(o:Order): return run(engine.order,o.symbol,o.side,o.qty,o.request_id)
@app.put('/api/rules')
def rules(r:Rules):
    engine.rules(r.model_dump())
    return r
@app.post('/api/news')
def news(n:News): return engine.news(news_id(n.title,n.url),n.title,n.url,n.symbol)

@app.get('/api/integrations')
def integrations(): return {**news_service.status(),'broker':broker.status()}
@app.post('/api/news/collect')
async def collect(): return await news_service.collect()
@app.post('/api/news/{item_id}/analyze')
async def analyze_news(item_id:str):
    item=engine.get_news(item_id)
    if not item: raise HTTPException(404,'뉴스를 찾을 수 없습니다')
    try:
        result=await analyze(item['title'],item['url'])
    except ValueError as exc:
        raise HTTPException(409,str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502,'AI 연결에 실패했습니다. API 설정과 연결 상태를 확인하세요') from exc
    engine.save_analysis(item_id,result)
    return result
@app.get('/api/history/{symbol}')
def history(symbol:str): return engine.history(symbol)

@app.get('/api/broker/accounts')
async def accounts():
    try:
        async with broker_settings_lock:
            data=await broker.read('/api/v1/accounts')
        return [{'account_seq':x['accountSeq'],'account_type':x['accountType']} for x in data]
    except ValueError as exc: raise HTTPException(409,str(exc)) from exc
    except Exception as exc: raise HTTPException(502,'토스 계좌 조회 실패. 인증·허용 IP를 확인하세요') from exc
@app.post('/api/broker/holdings/refresh')
async def refresh_holdings():
    try:
        async with broker_settings_lock:
            broker.holdings=await broker.read('/api/v1/holdings',account=True)
        return broker.holdings
    except ValueError as exc: raise HTTPException(409,str(exc)) from exc
    except Exception as exc: raise HTTPException(502,'토스 보유종목 조회 실패. 인증·허용 IP를 확인하세요') from exc
@app.get('/api/broker/holdings')
def holdings(): return broker.holdings
@app.get('/api/market/quotes')
def market_quotes(): return engine.market_state()
@app.get('/api/market/history/{symbol}')
def market_history(symbol:str): return engine.market_history(symbol)

@app.get("/lab")
def lab(): return FileResponse(static/"lab.html")

@app.get('/lab/comparison')
def lab_comparison(): return FileResponse(static/'comparison.html')

from app.auth import AuthSettings, AuthStore, install_auth
install_auth(app, AuthStore(os.getenv('INVESTPILOT_AUTH_DB','data/auth.db')), AuthSettings.environment(), static)
