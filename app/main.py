import os
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from app.engine import Engine

app = FastAPI(title='InvestPilot', version='0.1.0')
engine = Engine(os.environ.get('INVESTPILOT_DB','data/investpilot.db'))
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
def news(n:News): return engine.news(n.news_id,n.title,n.url,n.symbol)
