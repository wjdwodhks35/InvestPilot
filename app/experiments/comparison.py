"""Read-only views over local experiment artifacts; no inference or order calls."""
import csv
import hashlib
import json
import math
from datetime import date, timedelta
from pathlib import Path
from app.experiments.scoring import score_forecast

ROOT = Path('data/experiments/top50-v1')
DAYS = (7, 30, 90)
LABELS = ('down', 'flat', 'up')


def read(path):
    return json.loads(path.read_text())


def snapshot(root=None):
    root = Path(root or ROOT)
    directories = sorted(root.glob('????-??-??'), reverse=True)
    directory = next((p for p in directories if (p/'evaluation-private.json').exists()), None)
    if directory is None:
        return {'ready': False, 'message': '실험 결과가 없습니다. Drive의 실험 ZIP을 data/experiments/top50-v1에 복원하세요.'}
    evaluation = read(directory/'evaluation-private.json')
    configuration = read(directory/'configuration.json')
    predictions = {}
    skipped = 0
    for path in directory.glob('batch-*-forecasts.json'):
        try:
            saved = read(path)
            context = read(path.with_name(path.name.replace('-forecasts', '-input')))
            digest = hashlib.sha256(json.dumps(context, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()
            if saved['identity']['input_sha256'] != digest:
                raise ValueError('Input changed')
            items = saved['prediction']['forecasts']
            expected = {(s['symbol'], d) for s in context['stocks'] for d in DAYS}
            keys = {(f['symbol'], f['days']) for f in items}
            if keys != expected or len(items) != len(expected):
                raise ValueError('Incomplete batch')
            for item in items:
                probs = [item[k] for k in LABELS]
                if any(isinstance(x, bool) or not isinstance(x, int) or not 0 <= x <= 100 for x in probs) or sum(probs) != 100:
                    raise ValueError('Invalid probabilities')
                ret = item['expected_return_pct']
                if isinstance(ret, bool) or not isinstance(ret, (int, float)) or not math.isfinite(ret) or not -100 <= ret <= 1000:
                    raise ValueError('Invalid return')
            for item in items:
                predictions[(item['symbol'], item['days'])] = {'status': 'ok',
                    'prediction': max(LABELS, key=lambda k: item[k]),
                    'expected_return_pct': item['expected_return_pct'],
                    'probabilities': {k: item[k]/100 for k in LABELS}}
        except (OSError, ValueError, KeyError, TypeError):
            skipped += 1  # An in-flight write is retried by the next dashboard refresh.
    rows = []
    for source in evaluation:
        actual = source['actual']
        row = {k: source[k] for k in ('symbol', 'name', 'days')}
        row.update(actual=actual, logistic=source['logistic'],
                   ollama=predictions.get((source['symbol'], source['days']), {'status': 'pending'}), scores={})
        if actual['status'] == 'observed':
            for model in ('logistic', 'ollama'):
                f = row[model]
                if f['status'] == 'ok':
                    row['scores'][model] = score_forecast(actual['return_pct'], f['prediction'], f['expected_return_pct'])
        rows.append(row)
    metrics = {}
    for horizon in DAYS:
        matched = [r for r in rows if r['days'] == horizon and all(m in r['scores'] for m in ('logistic', 'ollama'))]
        n = len(matched)
        metrics[str(horizon)] = {'evaluated': n, 'models': {m: {
            'direction_accuracy': sum(r['scores'][m]['direction_correct'] for r in matched)/n if n else None,
            'return_accuracy': sum(r['scores'][m]['return_correct'] for r in matched)/n if n else None,
            'mae_pp': sum(r['scores'][m]['absolute_error_pp'] for r in matched)/n if n else None,
        } for m in ('logistic', 'ollama')},
            'always_up_accuracy': sum(r['actual']['direction']=='up' for r in matched)/n if n else None,
            'always_down_accuracy': sum(r['actual']['direction']=='down' for r in matched)/n if n else None}
    completed = {s for s, d in predictions if all((s, h) in predictions for h in DAYS)}
    total = configuration['universe_size']
    prices = {}
    start = (date.fromisoformat(directory.name)-timedelta(days=90)).isoformat()
    end = (date.fromisoformat(directory.name)+timedelta(days=100)).isoformat()
    for symbol in {r['symbol'] for r in rows}:
        path = root/'prices'/f'{symbol}.csv'
        if not path.exists(): continue
        with path.open() as f:
            prices[symbol] = [{'date': r['date'], 'close': float(r['close'])} for r in csv.DictReader(f)
                              if start <= r['date'] <= end]
    return {'ready': True, 'test_date': directory.name, 'universe_as_of': configuration['source_universe_retrieved_at'],
            'total_stocks': total, 'completed_stocks': len(completed), 'completed_forecasts': len(predictions),
            'complete': len(completed) == total, 'skipped_batches': skipped,
            'model': 'Qwen3 4B · Ollama', 'rows': rows, 'metrics': metrics, 'prices': prices,
            'limitations': ['현재 시총 상위 50개 종목·우선주 포함. 과거 당시 상위 50개가 아닙니다.',
                '2026-06-01 한 날짜의 실험이며 종목 간 결과는 서로 연관됩니다.',
                '과거 가격·관련 종목 기반이며 뉴스는 아직 포함되지 않았습니다.',
                '확률은 보정되지 않은 추정치입니다. LLM 학습 기억의 미래 정보는 배제할 수 없습니다.',
                '변화율 오차는 ±5%포인트이며 방향과 부호도 맞아야 합니다. 실제 +3%는 예상 +1~+8%를 인정합니다.']}
