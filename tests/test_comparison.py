import hashlib
import json
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.experiments import comparison
from app.experiments.api import router


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def fixture(root):
    directory = root/'2026-06-01'
    write(directory/'configuration.json', {'universe_size': 2, 'source_universe_retrieved_at': '2026-10-06'})
    rows = []
    for s in ('000001', '000002'):
        for d in (7,30,90):
            rows.append(dict(symbol=s,name='종목 '+s,days=d,actual=dict(status='observed',return_pct=3,direction='up'),
                             logistic=dict(status='ok',prediction='up',expected_return_pct=2)))
    write(directory/'evaluation-private.json', rows)
    context = {'stocks': [{'symbol':'000001'}]}
    digest=hashlib.sha256(json.dumps(context,ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()
    write(directory/'batch-00-input.json',context)
    write(directory/'batch-00-forecasts.json', {'identity':{'input_sha256':digest},'prediction':{'forecasts':[
        dict(symbol='000001',days=d,up=70,flat=10,down=20,expected_return_pct=4) for d in (7,30,90)]}})
    return directory


def test_partial_results_compare_same_stocks_and_never_fill_missing(tmp_path):
    fixture(tmp_path)
    result=comparison.snapshot(tmp_path)
    assert result['completed_stocks']==1 and result['completed_forecasts']==3
    assert not result['complete']
    assert result['metrics']['7']['evaluated']==1
    assert result['metrics']['7']['models']['ollama']['return_accuracy']==1
    pending=next(r for r in result['rows'] if r['symbol']=='000002')
    assert pending['ollama']=={'status':'pending'} and 'ollama' not in pending['scores']


def test_partial_write_and_stale_input_are_not_evaluated(tmp_path):
    directory=fixture(tmp_path)
    (directory/'batch-00-forecasts.json').write_text('{')
    assert comparison.snapshot(tmp_path)['completed_stocks']==0
    fixture(tmp_path)
    write(directory/'batch-00-input.json', {'stocks':[{'symbol':'000001'}],'changed':True})
    result=comparison.snapshot(tmp_path)
    assert result['completed_forecasts']==0 and result['skipped_batches']==1


def test_read_only_api_with_no_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(comparison,'ROOT',tmp_path)
    app=FastAPI();app.include_router(router)
    with TestClient(app) as client:
        r=client.get('/api/experiments/top50/comparison')
        assert r.status_code==200 and r.json()['ready'] is False
        assert client.post('/api/experiments/top50/comparison').status_code==405
    assert not list(tmp_path.iterdir())
