"""User-assigned themes, valued separately in each trading currency."""
from collections import defaultdict
from decimal import Decimal,InvalidOperation
from app.engine import WATCHLIST


def breakdown(holdings,categories):
    defaults={s:t for s,n,t in WATCHLIST}
    groups=defaultdict(lambda:defaultdict(Decimal));totals=defaultdict(Decimal)
    for item in (holdings or {}).get('items',[]):
        currency=item.get('currency','unknown')
        try: amount=Decimal(str(item['quantity']))*Decimal(str(item['lastPrice']))
        except (KeyError,InvalidOperation):continue
        if not amount.is_finite() or amount<0:continue
        category=categories.get(item['symbol'],defaults.get(item['symbol'],'미분류'))
        groups[currency][category]+=amount;totals[currency]+=amount
    return {'loaded':holdings is not None,'currencies':[{'currency':cur,'total':str(totals[cur]),
        'categories':[{'category':cat,'value':str(value),'weight_pct':float(value/totals[cur]*100) if totals[cur] else 0}
            for cat,value in sorted(values.items(),key=lambda x:x[1],reverse=True)]}
        for cur,values in sorted(groups.items())],
        'note':'평가금액(수량×현재가) 기준. 통화별 비중이며 환율 합산하지 않습니다. 기본 관심종목 외에는 직접 분류하세요.'}
