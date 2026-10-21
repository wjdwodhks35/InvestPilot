"""Saved user assumptions, not a dividend forecast or a security recommendation."""
from decimal import Decimal, ROUND_FLOOR
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from app.portfolio import exchange_rate


class DividendScenario(BaseModel):
    model_config = ConfigDict(extra='forbid')
    symbol: str = Field(default='', max_length=20, pattern=r'^[A-Za-z0-9.\-]*$')
    investment: Decimal = Field(gt=0, le=10**12, max_digits=20, decimal_places=6)
    currency: Literal['KRW','USD']
    annual_yield_pct: Decimal = Field(ge=0, le=100, max_digits=10, decimal_places=6)
    assumed_tax_pct: Decimal = Field(default=Decimal(0), ge=0, le=100, max_digits=10, decimal_places=6)
    payments_per_year: Literal[1,2,4,12] = 4
    share_price: Decimal | None = Field(default=None, gt=0, le=10**12, max_digits=20, decimal_places=6)
    fractional: bool = False


def estimate(scenario, fx=None):
    shares = None
    invested = scenario.investment
    if scenario.share_price is not None:
        shares = invested/scenario.share_price
        if not scenario.fractional:
            shares = shares.to_integral_value(rounding=ROUND_FLOOR)
        invested = scenario.investment if scenario.fractional else shares*scenario.share_price
    gross = invested*scenario.annual_yield_pct/100
    net = gross*(1-scenario.assumed_tax_pct/100)
    valid_fx = exchange_rate(fx)
    converted=[]
    for currency in ('KRW','USD'):
        factor = (Decimal(1) if currency == scenario.currency else
                  Decimal(valid_fx['rate']) if valid_fx and currency == 'KRW' else
                  1/Decimal(valid_fx['rate']) if valid_fx else None)
        values = dict(annual_gross=gross, annual_net=net, monthly_average_net=net/12,
                      per_payment_net=net/scenario.payments_per_year,
                      invested=invested, unspent=scenario.investment-invested)
        converted.append(dict(currency=currency, **{key:str(value*factor) if factor is not None else None for key,value in values.items()}))
    return dict(assumptions=scenario.model_dump(mode='json'),
                shares=str(shares) if shares is not None else None,
                converted=converted, fx=valid_fx,
                note='사용자가 입력한 연 배당률·세율이 유지되고 1년 내내 보유한다는 단순 가정입니다. '
                     '월평균은 연간 예상액÷12이며 실제 매월 지급액이 아닙니다. 1회당 금액은 균등 지급 가정입니다. '
                     '배당 확정·지급 일정·배당락 자격을 확인한 결과가 아니며 감액·중단될 수 있습니다. '
                     '주가 미입력 시 투자금 전액에 배당률을 적용합니다. 세율 0%는 세전 가정이며 실제 세법을 자동 적용하지 않습니다.')
