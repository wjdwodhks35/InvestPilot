import numpy as np
import pandas as pd
import pytest
import json
import httpx
from scripts.top50_experiment import (past_frames, related_symbols, compact_stats,
    train_past, actual_result, ForecastItem, paper_portfolio, ForecastBatch, call_model)


def samples():
    dates = pd.bdate_range('2023-01-01', periods=700).strftime('%Y-%m-%d')
    close = np.round(100 + 8 * np.sin(np.arange(700) / 10))
    frame = pd.DataFrame(dict(date=dates, open=close, close=close, high=close+1,
                              low=close-1, volume=np.ones(700)*1000))
    return {'000001': frame, '000002': frame.copy()}


def test_future_changes_do_not_change_features_peers_or_training():
    frames = samples(); cutoff = frames['000001'].iloc[500].date
    past = past_frames(frames, cutoff)
    peer = related_symbols('000001', past)
    fitted = train_past('000001', peer, past, 7)
    assert fitted['status'] == 'ok'
    assert fitted['latest_label_date'] < cutoff
    frames['000002'].loc[frames['000002'].date >= cutoff, 'close'] = 999999
    changed = past_frames(frames, cutoff)
    assert peer == related_symbols('000001', changed)
    assert compact_stats(past['000002']) == compact_stats(changed['000002'])
    assert fitted == train_past('000001', peer, changed, 7)
    actual = actual_result(frames['000001'], cutoff, 7)
    assert actual['paper_entry_date'] >= cutoff
    assert actual['exit_date'] > cutoff


def test_direction_and_magnitude_are_validated_separately():
    ForecastItem(symbol='000001', days=7, up=60, flat=10, down=30, expected_return_pct=2)
    ForecastItem(symbol='000001', days=7, up=60, flat=10, down=30, expected_return_pct=-2)
    with pytest.raises(ValueError):
        ForecastItem(symbol='000001', days=7, up=60, flat=10, down=20, expected_return_pct=2)


def test_paper_allocation_stays_within_100000_and_does_not_use_reference_fill():
    rows=[]
    for n in range(50):
        rows.append(dict(symbol=str(n), days=7, actual=dict(status='observed',exit_close=110,
            paper_entry_open=100,reference_close=50),ollama=dict(status='ok',prediction='up',expected_return_pct=5)))
    portfolio=paper_portfolio(rows,'ollama',7)
    assert sum(x['allocated_krw'] for x in portfolio['holdings'])==100000
    assert 109000 < portfolio['final_krw'] < 110000
    assert paper_portfolio(rows[:49],'ollama',7)['status']=='incomplete_universe'


def test_model_repairs_invalid_sum_without_receiving_actual_labels():
    count = 0
    context = {'stocks': [{'symbol': '000001'}]}
    def reply(request):
        nonlocal count
        count += 1
        payload = json.loads(request.content)
        assert 'actual' not in json.dumps(payload)
        if count == 2: assert 'Validation error:' in payload['messages'][-1]['content']
        return httpx.Response(200, json={'done': True, 'message': {'content': json.dumps({'forecasts': [
            dict(symbol='000001', days=7, up=60, flat=10, down=20 if count==1 else 30, expected_return_pct=2)]})}})
    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        parsed, raw = call_model(client, 'qwen3:4b', ForecastBatch, 'Research only', context, 1000)
    assert parsed.forecasts[0].expected_return_pct == 2
    assert len(raw['validation_attempts']) == 2
