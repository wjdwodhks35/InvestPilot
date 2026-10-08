import httpx
from scripts.ollama_remote_paper import http_failure_message


def error(path,code):
    request=httpx.Request('GET','https://example.test'+path)
    response=httpx.Response(code,request=request,json={'detail':'private-secret'})
    return httpx.HTTPStatusError('private-secret',request=request,response=response)


def test_stale_quote_is_not_presented_as_login_failure():
    message=http_failure_message(error('/api/experiments/ai/worker-context',409))
    assert '60초' in message and '최신 시세 없음' in message
    assert '인증 실패' not in message and 'private-secret' not in message


def test_http_errors_identify_service_and_code_without_raw_body():
    for path,code,expected in [('/api/auth/login',401,'로그인'),('/api/market/refresh',502,'토스 시세'),('/api/experiments/ai/worker-context',403,'접근 거부')]:
        message=http_failure_message(error(path,code))
        assert expected in message and str(code) in message
        assert 'private-secret' not in message
