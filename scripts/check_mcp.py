"""Offline preflight: never imports the app, connects to a DB or prints values."""
import json
import os
from urllib.parse import urlsplit


def fixed_https(value, *, origin=False):
    try:
        parts = urlsplit(value)
        return bool(parts.scheme == 'https' and parts.hostname and parts.port != 0
                    and not parts.username and not parts.password
                    and not parts.query and not parts.fragment
                    and not any(c.isspace() for c in value)
                    and (not origin or not parts.path))
    except (ValueError, TypeError):
        return False


def inspect(environment):
    """Inspect a supplied mapping. All output messages are fixed, never input values."""
    checks = []
    def check(name, valid, message):
        checks.append({'check': name, 'status': 'pass' if valid else 'fail', 'message': message})

    check('enabled', environment.get('INVESTPILOT_MCP_ENABLED', 'false').lower() == 'true',
          'MCP 활성화 여부. 준비 중에는 비활성 상태를 유지해도 됩니다.')
    check('web_auth', environment.get('INVESTPILOT_AUTH_ENABLED', 'true').lower() == 'true'
          and environment.get('INVESTPILOT_AUTH_SECURE_COOKIE', 'true').lower() == 'true',
          '웹 로그인 보호와 Secure 쿠키가 필요합니다.')
    origin = (environment.get('INVESTPILOT_PUBLIC_ORIGIN')
              or environment.get('RENDER_EXTERNAL_URL', '')).rstrip('/')
    check('public_origin', fixed_https(origin, origin=True), '고정 HTTPS 웹 원본 주소가 필요합니다.')
    resource = environment.get('INVESTPILOT_MCP_RESOURCE', '')
    check('resource', fixed_https(resource) and resource == origin + '/mcp',
          'MCP 리소스는 웹 원본 주소의 /mcp와 정확히 일치해야 합니다.')
    check('issuer', fixed_https(environment.get('INVESTPILOT_MCP_ISSUER', '')),
          '정확한 HTTPS OAuth issuer가 필요합니다. 실제 제공자 일치 여부는 별도 검증합니다.')
    check('jwks', fixed_https(environment.get('INVESTPILOT_MCP_JWKS_URL', '')),
          '고정 HTTPS JWKS 주소가 필요합니다. 실제 키 응답은 별도 검증합니다.')
    clients = environment.get('INVESTPILOT_MCP_CLIENT_IDS', '').split(',')
    check('clients', bool(clients) and all(c and not any(x.isspace() for x in c) for c in clients),
          '공백 없는 허용 OAuth Client ID 목록이 필요합니다.')
    # Parsing and key validation are local operations; never instantiate storage classes.
    database_ok = False
    try:
        from psycopg.conninfo import conninfo_to_dict
        url = environment.get('INVESTPILOT_DATABASE_URL', '')
        if url.startswith(('postgres://', 'postgresql://')):
            info = conninfo_to_dict(url)
            database_ok = bool(info.get('host') and info.get('dbname')
                               and info.get('sslmode') in ('require', 'verify-ca', 'verify-full'))
    except Exception:
        pass
    check('database', database_ok, 'Render용 PostgreSQL 주소와 TLS가 필요합니다. 접속·영속성은 검증하지 않습니다.')
    key_ok = False
    try:
        from cryptography.fernet import Fernet
        Fernet(environment.get('INVESTPILOT_SETTINGS_KEY', '').encode())
        key_ok = True
    except Exception:
        pass
    check('settings_key', key_ok, '기존 설정 암호화 키의 유효한 형식이 필요합니다. 새 키를 생성하지 마세요.')
    return {'configuration_ready': all(c['status'] == 'pass' for c in checks),
            'live_connection_verified': False, 'checks': checks,
            'remaining': ['운영 DB 위치·영속성과 기존 데이터 확인', 'OAuth discovery·PKCE·클라이언트 등록 확인',
                          '소유권·동의 확인 후 사용자 연결', '승인된 배포 후 실제 ChatGPT 조회·격리·해제 검증']}


def main():
    # Only the current process environment is read. No automatic .env search or writes.
    report = inspect(os.environ)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['configuration_ready'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
