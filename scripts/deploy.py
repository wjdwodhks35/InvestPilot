"""Production entrypoint: validate HTTPS, bootstrap the owner, and start ASGI."""
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit
from app.auth import AuthStore

SECRET_KEY='INVESTPILOT_INITIAL_PASSWORD'


def prepare(environment):
    env=dict(environment)
    origin=env.get('INVESTPILOT_PUBLIC_ORIGIN') or env.get('RENDER_EXTERNAL_URL','')
    origin=origin.rstrip('/')
    parts=urlsplit(origin)
    if parts.scheme!='https' or not parts.hostname or parts.username or parts.password or parts.path or parts.query or parts.fragment:
        raise ValueError('배포용 HTTPS 주소가 필요합니다. PUBLIC_ORIGIN 또는 Render 외부 주소를 확인하세요.')
    if env.get('INVESTPILOT_AUTH_ENABLED','true').lower()!='true':
        raise ValueError('외부 배포에서는 로그인 보호를 켜야 합니다.')
    if env.get('INVESTPILOT_AUTH_SECURE_COOKIE','true').lower()!='true':
        raise ValueError('외부 배포에서는 Secure 쿠키를 켜야 합니다.')
    try:port=int(env.get('PORT','10000'))
    except ValueError as exc:raise ValueError('PORT는 숫자여야 합니다.') from exc
    if not 1<=port<=65535:raise ValueError('PORT는 1~65535 범위여야 합니다.')
    env.update(INVESTPILOT_PUBLIC_ORIGIN=origin,INVESTPILOT_AUTH_ENABLED='true',
               INVESTPILOT_AUTH_SECURE_COOKIE='true',WEB_CONCURRENCY='1')
    if env.get('INVESTPILOT_STORAGE_MODE') == 'postgres':
        from psycopg.conninfo import conninfo_to_dict
        database_url = env.get('INVESTPILOT_DATABASE_URL', '')
        if not database_url:
            raise ValueError('무료 배포에는 외부 DB 연결이 필요합니다. 비밀 DATABASE_URL 환경변수를 설정하세요.')
        try: info = conninfo_to_dict(database_url)
        except Exception as exc: raise ValueError('DB 연결 주소 형식을 확인하세요.') from exc
        if info.get('sslmode') not in ('require', 'verify-ca', 'verify-full'):
            raise ValueError('외부 DB 연결에는 TLS가 필요합니다.')
    data=Path(env.get('INVESTPILOT_DATA_DIR','data')).resolve()
    data.mkdir(parents=True,exist_ok=True)
    for key,name in [('INVESTPILOT_DB','investpilot.db'),('INVESTPILOT_AI_DB','ai-paper.db'),('INVESTPILOT_AUTH_DB','auth.db')]:
        path=Path(env.get(key,str(data/name))).resolve()
        if not path.is_relative_to(data):raise ValueError('배포 DB는 영구 데이터 경로 아래에 저장해야 합니다.')
        env[key]=str(path)
    store=AuthStore(env['INVESTPILOT_AUTH_DB'], database_url=env.get('INVESTPILOT_DATABASE_URL', ''))
    if not store.configured():
        password=env.get(SECRET_KEY,'')
        if not password:raise ValueError('최초 로그인 비밀번호를 서버의 비밀 환경변수에 설정하세요.')
        store.configure(env.get('INVESTPILOT_INITIAL_USERNAME','admin'),password)
    env.pop(SECRET_KEY,None)
    return env,origin,port


def main():
    try:environment,origin,port=prepare(os.environ)
    except ValueError as exc:
        print(str(exc),file=sys.stderr);return 1
    print('InvestPilot 운영 서버 시작',flush=True)
    print('플랫폼: '+origin+'/',flush=True)
    print('로그인: '+origin+'/login',flush=True)
    print('예측 비교: '+origin+'/lab/comparison',flush=True)
    # No plaintext bootstrap password is passed to the application process.
    os.execvpe(sys.executable,[sys.executable,'-m','uvicorn','app.main:app','--host','0.0.0.0',
                             '--port',str(port),'--workers','1'],environment)


if __name__=='__main__':raise SystemExit(main())
