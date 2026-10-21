import asyncio
import json
from datetime import datetime,timezone,timedelta
import httpx
import pytest
from app.dividend_market import DividendMarket,DividendUnavailable,DividendMarketQuote


def run(data, env=None):
    calls=[]
    def handler(request):
        calls.append(request)
        assert request.headers['X-Finnhub-Token']=='secret-test-token'
        assert 'token' not in request.url.params
        symbol=request.url.params['symbol']
        if request.url.path.endswith('/profile2'):
            return httpx.Response(200,json={'ticker':symbol,'currency':'USD'})
        if request.url.path.endswith('/metric'):
            return httpx.Response(200,json={'symbol':symbol,'metric':data})
        return httpx.Response(200,json={'c':100,'t':datetime.now(timezone.utc).timestamp()})
    async def perform():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            market=DividendMarket(env=env or {'FINNHUB_API_KEY':'secret-test-token'},client=client)
            first=await market.lookup('AAPL');second=await market.lookup('AAPL')
            assert first==second
            return first
    return asyncio.run(perform()),calls


def test_indicated_yield_is_automatic_and_cached():
    quote,calls=run({'dividendYieldIndicatedAnnual':1.25,'currentDividendYieldTTM':99})
    assert str(quote.annual_yield_pct)=='1.25' and quote.basis=='dividendYieldIndicatedAnnual'
    assert len(calls)==3 and quote.currency=='USD' and quote.share_price==100
    assert 'secret-test-token' not in quote.model_dump_json()


@pytest.mark.parametrize('data',[{}, {'currentDividendYieldTTM':4}, {'dividendYieldIndicatedAnnual':None},
                                {'dividendYieldIndicatedAnnual':'NaN'},{'dividendYieldIndicatedAnnual':True}])
def test_missing_or_invalid_forecast_never_falls_back(data):
    with pytest.raises(DividendUnavailable):run(data)


def test_explicit_zero_is_distinct_from_missing():
    quote,_=run({'dividendYieldIndicatedAnnual':0})
    assert quote.annual_yield_pct==0


def test_missing_configuration_and_unmapped_kr_no_requests():
    async def check():
        for env,symbol in [({},'AAPL'),({'FINNHUB_API_KEY':'key'},'005930')]:
            with pytest.raises(DividendUnavailable):await DividendMarket(env=env).lookup(symbol)
    asyncio.run(check())


def test_expired_snapshot_rejected():
    value=DividendMarketQuote(symbol='AAPL',provider_symbol='AAPL',currency='USD',annual_yield_pct=1,
        fetched_at=(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat())
    assert not value.fresh()


def test_provider_error_body_and_token_not_disclosed():
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(403,text='private-provider-body'))) as client:
            market=DividendMarket(env={'FINNHUB_API_KEY':'secret-token'},client=client)
            with pytest.raises(DividendUnavailable) as caught:await market.lookup('AAPL')
            assert 'private-provider-body' not in str(caught.value) and 'secret-token' not in str(caught.value)
    asyncio.run(check())
