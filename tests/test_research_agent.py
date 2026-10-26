import pytest
import json
import httpx
from app.experiments.research_agent import ResearchBrief, validate_brief, analyze


def test_analyst_citations_are_bounded_by_supplied_evidence():
    context = dict(test_date='2026-03-02', target_bars=[{'date': '2026-02-27'}], related_stocks=[])
    def brief(stamp):
        return ResearchBrief.model_validate(dict(cutoff_exclusive='2026-03-02',
            observations=[dict(symbol='005930', evidence_date=stamp, finding='가격 관찰')],
            limitations=['과거 뉴스 없음']))
    assert validate_brief(brief('2026-02-27'), context)
    with pytest.raises(ValueError):
        validate_brief(brief('2026-03-02'), context)
    with pytest.raises(ValueError):
        validate_brief(brief('2026-02-26'), context)


def test_analyst_uses_its_own_prompt_and_preserves_raw_response():
    context = dict(test_date='2026-03-02', target_bars=[{'date': '2026-02-27'}], related_stocks=[])
    content = dict(cutoff_exclusive='2026-03-02', observations=[], limitations=['과거 뉴스 없음'])
    def reply(request):
        body = json.loads(request.content)
        assert 'research analyst' in body['messages'][0]['content']
        assert 'failure_scenarios' in body['messages'][0]['content']
        assert 'critically review' in body['messages'][0]['content']
        assert json.loads(body['messages'][1]['content']) == context
        return httpx.Response(200, json={'done': True, 'message': {'content': json.dumps(content)}})
    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        brief, raw = analyze(client, 'qwen3:4b', context)
    assert brief.limitations == ['과거 뉴스 없음']
    assert raw['done']


def test_failure_scenarios_reject_fabricated_numbers_and_future_citations():
    context = dict(test_date='2026-03-02', target_bars=[{'date':'2026-02-27','close':10000,'volume':500}], related_stocks=[])
    citation = dict(symbol='005930', evidence_date='2026-02-27', field='close', value=10000)
    payload = dict(cutoff_exclusive='2026-03-02', observations=[], limitations=['가격 자료만 제공됨'],
        numeric_evidence=[citation.copy()], failure_scenarios=[dict(hypothesis='하락 추세 지속 가능성이라는 가정',
        early_warning='추가 가격 하락 여부 관찰', invalidation_condition='하락 가설을 지지하지 않는 후속 가격', evidence=[citation.copy()])])
    assert validate_brief(ResearchBrief.model_validate(payload), context)
    payload['failure_scenarios'][0]['evidence'][0]['value'] = 11000
    with pytest.raises(ValueError, match='numeric evidence'):
        validate_brief(ResearchBrief.model_validate(payload), context)
    payload['failure_scenarios'][0]['evidence'][0] = {**citation, 'evidence_date':'2026-03-03'}
    with pytest.raises(ValueError):
        validate_brief(ResearchBrief.model_validate(payload), context)
    payload['failure_scenarios'] = []
    payload['numeric_evidence'][0]['field'] = 'eps'
    with pytest.raises(ValueError):
        ResearchBrief.model_validate(payload)


def test_numeric_evidence_rejects_missing_values_and_wrong_symbols():
    context = dict(test_date='2026-03-02', target_bars=[{'date':'2026-02-27','close':10000}], related_stocks=[])
    for symbol, field in [('005930','volume'),('000660','close')]:
        brief = ResearchBrief.model_validate(dict(cutoff_exclusive='2026-03-02', observations=[], limitations=['자료 부족'],
            numeric_evidence=[dict(symbol=symbol,evidence_date='2026-02-27',field=field,value=10000)]))
        with pytest.raises(ValueError): validate_brief(brief, context)
