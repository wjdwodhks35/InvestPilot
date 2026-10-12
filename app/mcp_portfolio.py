"""Minimal broker data boundary. No account identifiers or model calls."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re
import httpx

class CappedStream(httpx.AsyncByteStream):
    def __init__(self, stream):
        self.stream = stream
    async def __aiter__(self):
        size = 0
        async for chunk in self.stream:
            size += len(chunk)
            if size > 2_000_000:
                raise ValueError('Broker response too large')
            yield chunk
    async def aclose(self):
        await self.stream.aclose()

class CappedTransport(httpx.AsyncBaseTransport):
    def __init__(self):
        self.inner = httpx.AsyncHTTPTransport(retries=0)
    async def handle_async_request(self, request):
        response = await self.inner.handle_async_request(request)
        response.stream = CappedStream(response.stream)
        return response
    async def aclose(self):
        await self.inner.aclose()


def snapshot(raw):
    items = raw.get('items') if isinstance(raw, dict) else None
    if not isinstance(items, list) or len(items) > 200:
        raise ValueError('Invalid holdings')
    positions = []
    totals = {}
    for row in items:
        if not isinstance(row, dict):
            raise ValueError('Invalid holding')
        symbol = row.get('symbol')
        currency = row.get('currency')
        if not isinstance(symbol, str) or not re.fullmatch(r'[A-Za-z0-9.\-]{1,20}', symbol):
            raise ValueError('Invalid symbol')
        if currency not in ('KRW', 'USD'):
            raise ValueError('Unsupported currency')
        try:
            qty = Decimal(str(row['quantity']))
            price = Decimal(str(row['lastPrice']))
        except (KeyError, InvalidOperation):
            raise ValueError('Invalid amount') from None
        if not qty.is_finite() or not price.is_finite() or not 0 <= qty <= 10**12 or not 0 <= price <= 10**12:
            raise ValueError('Invalid amount')
        value = qty * price
        positions.append(dict(symbol=symbol, currency=currency, quantity=str(qty),
                              last_price=str(price), value=str(value)))
        totals[currency] = totals.get(currency, Decimal(0)) + value
    for row in positions:
        total = totals[row['currency']]
        row['weight_pct'] = float(Decimal(row['value']) / total * 100) if total else 0
    return dict(retrieved_at=datetime.now(timezone.utc).isoformat(),
                price_timestamp=None, positions=positions,
                totals=[dict(currency=k, value=str(v)) for k, v in sorted(totals.items())],
                note='Read-only snapshot. Retrieval time is not market price time. Currencies are not combined.')

async def read_portfolio(manager, user_id):
    if not user_id:
        raise ValueError('Authenticated identity required')
    item = manager.get(user_id)
    async with item['lock']:
        # Reuse saved per-user credentials and the existing broker path allowlist.
        async with httpx.AsyncClient(transport=CappedTransport(), timeout=15, trust_env=False,
                                     follow_redirects=False, headers={'Accept-Encoding':'identity'}) as client:
            raw = await item['broker'].read('/api/v1/holdings', account=True, client=client)
    return snapshot(raw)
