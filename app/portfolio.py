"""Account-specific portfolio categories with Decimal valuation and explicit FX basis."""
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from app.engine import WATCHLIST


def amount(value):
    try:
        number = Decimal(str(value))
        return number if number.is_finite() and 0 <= number <= 10**12 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def exchange_rate(raw, now=None):
    """Only a currently valid USD -> KRW reference rate is usable."""
    try:
        now = now or datetime.now(timezone.utc)
        start = datetime.fromisoformat(raw['validFrom'].replace('Z', '+00:00'))
        end = datetime.fromisoformat(raw['validUntil'].replace('Z', '+00:00'))
        rate = amount(raw['rate'])
        if (raw['baseCurrency'] != 'USD' or raw['quoteCurrency'] != 'KRW' or not rate
                or not start.tzinfo or not end.tzinfo or not start <= now < end):
            return None
        return dict(rate=str(rate), valid_from=start.isoformat(), valid_until=end.isoformat())
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def total(values):
    return None if any(v is None for v in values) else sum(values, Decimal(0))


def metrics(costs, values):
    cost, value = total(costs), total(values)
    profit = value-cost if cost is not None and value is not None else None
    return dict(cost=str(cost) if cost is not None else None,
                value=str(value) if value is not None else None,
                profit=str(profit) if profit is not None else None,
                return_pct=float(profit/cost*100) if profit is not None and cost else None)


def breakdown(holdings, categories, fx=None, retrieved_at=None, now=None):
    defaults = {s:t for s,n,t in WATCHLIST}
    positions = []
    valid_fx = exchange_rate(fx, now)
    for item in (holdings or {}).get('items', []):
        currency = item.get('currency')
        qty, price, average = (amount(item.get(k)) for k in ('quantity','lastPrice','averagePurchasePrice'))
        value = qty*price if qty is not None and price is not None else None
        cost = qty*average if qty is not None and average is not None else None
        symbol = item.get('symbol', '')
        category = categories.get(symbol, defaults.get(symbol, '미분류'))
        positions.append(dict(symbol=symbol, name=item.get('name') or symbol, currency=currency,
                              category=category, quantity=str(qty) if qty is not None else None,
                              average_price=str(average) if average is not None else None,
                              last_price=str(price) if price is not None else None,
                              cost=cost, value=value))
    native = []
    for currency in sorted({str(p['currency']) for p in positions}):
        members = [p for p in positions if str(p['currency']) == currency]
        summary = metrics([p['cost'] for p in members], [p['value'] for p in members])
        groups = []
        for category in sorted({p['category'] for p in members}):
            rows = [p for p in members if p['category'] == category]
            group = metrics([p['cost'] for p in rows], [p['value'] for p in rows])
            base, value = summary['value'], group['value']
            weight = float(Decimal(value)/Decimal(base)*100) if base and Decimal(base) and value is not None else None
            groups.append(dict(category=category, weight_pct=weight, **group))
        groups.sort(key=lambda g: Decimal(g['value'] or 0), reverse=True)
        native.append(dict(currency=currency, total=summary['value'], categories=groups, **summary))
    converted = []
    for target in ('KRW', 'USD'):
        rows = []
        for p in positions:
            factor = (Decimal(1) if p['currency'] == target else
                      Decimal(valid_fx['rate']) if valid_fx and p['currency']=='USD' and target=='KRW' else
                      1/Decimal(valid_fx['rate']) if valid_fx and p['currency']=='KRW' and target=='USD' else None)
            rows.append(dict(**{k:v for k,v in p.items() if k not in ('cost','value')},
                             cost=p['cost']*factor if p['cost'] is not None and factor is not None else None,
                             value=p['value']*factor if p['value'] is not None and factor is not None else None))
        groups=[]
        for category in sorted({p['category'] for p in rows}):
            members=[p for p in rows if p['category']==category]
            groups.append(dict(category=category, count=len(members),
                               **metrics([p['cost'] for p in members],[p['value'] for p in members])))
        converted.append(dict(currency=target, categories=groups,
                              positions=[dict(**{k:v for k,v in p.items() if k not in ('cost','value')},
                                              **metrics([p['cost']],[p['value']])) for p in rows],
                              **metrics([p['cost'] for p in rows],[p['value'] for p in rows])))
    return dict(loaded=holdings is not None, currencies=native, converted=converted,
                assignments=categories, fx=valid_fx, retrieved_at=retrieved_at,
                note='보유 수량×평균 매입가를 원금으로 계산한 미실현 평가손익입니다. 현금·매도 실현손익·수수료·세금은 제외합니다. '
                     '두 통화 환산에는 같은 현재 참고 환율을 적용하며 매입 당시 환율을 반영한 실제 원화 손익과 다릅니다. '
                     '원금·가격·환율이 없으면 해당 합계는 확인 필요로 표시합니다.')
