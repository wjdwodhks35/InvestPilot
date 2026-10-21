"""Bounded, cached Finnhub indicated annual dividend lookup. No trading or model calls."""
import asyncio
import json
import os
import re
import time
from collections import OrderedDict
from datetime import datetime, timezone
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field
import httpx


class DividendMarketQuote(BaseModel):
    model_config = ConfigDict(extra='forbid')
    symbol: str
    provider_symbol: str
    currency: str
    annual_yield_pct: Decimal = Field(ge=0,le=100,allow_inf_nan=False)
    share_price: Decimal | None = Field(default=None,gt=0,le=10**12,allow_inf_nan=False)
    price_at: str | None = None
    fetched_at: str
    source: str = 'Finnhub'
    basis: str = 'dividendYieldIndicatedAnnual'

    def fresh(self):
        try:
            age=(datetime.now(timezone.utc)-datetime.fromisoformat(self.fetched_at)).total_seconds()
            return self.source=='Finnhub' and self.basis=='dividendYieldIndicatedAnnual' and 0<=age<=3600
        except (ValueError,TypeError):
            return False


class DividendUnavailable(ValueError):
    pass


class DividendMarket:
    def __init__(self, env=None, client=None, clock=time.monotonic):
        self.env=os.environ if env is None else env
        self.client,self.clock=client,clock
        self.cache=OrderedDict();self.attempts=OrderedDict();self.lock=asyncio.Lock()

    async def request(self, client, path, symbol):
        async with client.stream('GET','https://finnhub.io/api/v1/'+path,
                                 params={'symbol':symbol,**({'metric':'all'} if path=='stock/metric' else {})},
                                 headers={'X-Finnhub-Token':self.env['FINNHUB_API_KEY']}) as response:
            response.raise_for_status()
            body=bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body)>1_000_000:
                    raise DividendUnavailable('배당 데이터 응답 크기를 확인하세요.')
        value=json.loads(body)
        if not isinstance(value,dict):
            raise DividendUnavailable('배당 데이터 형식을 확인하세요.')
        return value

    async def lookup(self, symbol):
        if not re.fullmatch(r'[A-Za-z0-9.\-]{1,20}',symbol):
            raise DividendUnavailable('종목 코드를 확인하세요.')
        # Numeric KR symbols require a verified provider symbol mapping; do not guess exchanges.
        try:
            mapping=json.loads(self.env.get('INVESTPILOT_DIVIDEND_SYMBOL_MAP','{}'))
            mapped=mapping.get(symbol)
            provider_symbol=mapped if isinstance(mapped,str) else symbol if not symbol.isdigit() else None
            if not provider_symbol or not re.fullmatch(r'[A-Za-z0-9.\-]{1,40}',provider_symbol):
                raise ValueError()
        except (ValueError,TypeError,AttributeError):
            raise DividendUnavailable('이 종목은 배당 데이터 제공처의 종목 연결이 필요합니다.') from None
        if not self.env.get('FINNHUB_API_KEY'):
            raise DividendUnavailable('자동 배당 조회 제공처가 아직 설정되지 않았습니다.')
        async with self.lock:
            now=self.clock()
            cached=self.cache.get(provider_symbol)
            if cached and now-cached[0]<1800:
                quote=cached[1].model_copy(update={'symbol':symbol})
                if quote.fresh():return quote
            # Public data only, but avoid repeated failures/provider quota consumption.
            if self.attempts.get(provider_symbol,0)>now:
                raise DividendUnavailable('잠시 후 배당 데이터를 다시 조회하세요.')
            recent=[v for v in self.attempts.values() if v>now]
            if len(recent)>=10:
                raise DividendUnavailable('배당 데이터 조회가 많습니다. 잠시 후 다시 시도하세요.')
            self.attempts[provider_symbol]=now+60
            while len(self.attempts)>256:self.attempts.popitem(last=False)
            try:
                async def fetch(client):
                    profile=await self.request(client,'stock/profile2',provider_symbol)
                    currency=profile.get('currency')
                    if currency not in ('KRW','USD'):
                        raise DividendUnavailable('이 종목의 원화·달러 통화 정보를 확인할 수 없습니다.')
                    if profile.get('ticker')!=provider_symbol:
                        raise DividendUnavailable('제공처 종목 코드가 일치하지 않습니다.')
                    data=await self.request(client,'stock/metric',provider_symbol)
                    if data.get('symbol')!=provider_symbol:
                        raise DividendUnavailable('제공처 종목 코드가 일치하지 않습니다.')
                    rate=data.get('metric',{}).get('dividendYieldIndicatedAnnual')
                    if rate is None or isinstance(rate,bool):
                        raise DividendUnavailable('이 종목의 예상 연 배당률 자료가 없습니다.')
                    # Trailing/TTM and past annual dividend fields are deliberately not substituted.
                    price,price_at=None,None
                    try:
                        quote=await self.request(client,'quote',provider_symbol)
                        value=Decimal(str(quote.get('c')))
                        stamp=datetime.fromtimestamp(quote['t'],timezone.utc)
                        age=(datetime.now(timezone.utc)-stamp).total_seconds()
                        if value.is_finite() and 0<value<=10**12 and 0<=age<=7*86400:
                            price,price_at=value,stamp.isoformat()
                    except Exception:
                        pass
                    return DividendMarketQuote(symbol=symbol,provider_symbol=provider_symbol,currency=currency,
                        annual_yield_pct=rate,share_price=price,price_at=price_at,
                        fetched_at=datetime.now(timezone.utc).isoformat())
                if self.client is not None:
                    result=await asyncio.wait_for(fetch(self.client),timeout=25)
                else:
                    async with httpx.AsyncClient(timeout=8,trust_env=False,follow_redirects=False) as client:
                        result=await asyncio.wait_for(fetch(client),timeout=25)
                self.cache[provider_symbol]=(now,result)
                while len(self.cache)>128:self.cache.popitem(last=False)
                return result
            except DividendUnavailable:
                raise
            except Exception:
                raise DividendUnavailable('배당 데이터 조회에 실패했습니다. 제공처 설정과 지원 여부를 확인하세요.') from None
