import pandas as pd
import math
from scripts.ollama_history import build_input, evaluate, Forecasts, logistic_before
import pytest


def test_historical_inputs_strictly_before_date(tmp_path):
    dates = pd.bdate_range('2023-01-01', periods=500)
    frame = pd.DataFrame({'date': dates.strftime('%Y-%m-%d'), 'open': 100,
        'high': 110, 'low': 90, 'close': [round(100 + 8 * math.sin(i / 10)) for i in range(500)], 'volume': 1000})
    frame.to_csv(tmp_path / 'prices.csv', index=False)
    frame.to_csv(tmp_path / 'peer_000660.csv', index=False)
    cutoff = frame.iloc[400].date
    context, past = build_input(tmp_path, cutoff)
    assert past.date.max() < cutoff
    assert all(r['date'] < cutoff for r in context['target_bars'])
    assert all(r['date'] < cutoff for r in context['related_stocks'][0]['bars'])
    altered = frame.copy()
    altered.loc[altered.date >= cutoff, 'close'] = 999999
    altered.to_csv(tmp_path / 'prices.csv', index=False)
    same, same_past = build_input(tmp_path, cutoff)
    assert context == same
    assert logistic_before(past, cutoff, 7) == logistic_before(same_past, cutoff, 7)
    assert logistic_before(past, cutoff, 7)['last_training_label_date'] < cutoff
    actual = evaluate(frame, context, 7)
    assert actual['date'] >= (pd.Timestamp(cutoff) + pd.Timedelta(days=7)).strftime('%Y-%m-%d')


def test_forecast_validation():
    with pytest.raises(ValueError):
        Forecasts.model_validate({'forecasts': [dict(days=7, up=40, flat=40, down=20, expected_return_pct=1,
            reason='test', risks='test')] * 3})
