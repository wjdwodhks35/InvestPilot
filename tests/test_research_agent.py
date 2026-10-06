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
        assert json.loads(body['messages'][1]['content']) == context
        return httpx.Response(200, json={'done': True, 'message': {'content': json.dumps(content)}})
    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        brief, raw = analyze(client, 'qwen3:4b', context)
    assert brief.limitations == ['과거 뉴스 없음']
    assert raw['done']
