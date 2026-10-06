"""Start the platform, show URLs, and open its login screen after readiness."""
import argparse
import getpass
import os
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from dotenv import load_dotenv
from app.auth import AuthSettings, AuthStore

ROOT=Path(__file__).resolve().parents[1]


def ensure_owner(store):
    if store.configured(): return
    if not sys.stdin.isatty():
        raise ValueError('로그인 계정이 없습니다. 먼저 python -m scripts.configure_auth --username admin을 실행하세요.')
    print('첫 실행입니다. 로그인 계정과 비밀번호를 설정합니다.',flush=True)
    username=input('계정 이름 [admin]: ').strip() or 'admin'
    password=getpass.getpass('비밀번호 (12자 이상): ')
    if password!=getpass.getpass('비밀번호 확인: '): raise ValueError('비밀번호가 일치하지 않습니다.')
    store.configure(username,password)
    print('계정을 설정했습니다. 비밀번호는 저장 파일이나 실행 로그에 표시되지 않습니다.',flush=True)


def local_url(port):
    return f'http://127.0.0.1:{port}'


def launch_environment(source):
    environment=dict(source)
    public=environment.get('INVESTPILOT_PUBLIC_ORIGIN','').rstrip('/')
    external=bool(public and urlsplit(public).hostname not in ('localhost','127.0.0.1','::1'))
    if not external:
        # Only the loopback-bound HTTP child is affected; .env is not modified.
        environment['INVESTPILOT_AUTH_SECURE_COOKIE']='false'
    return environment


def ensure_port(port):
    try:
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as listener:
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(('127.0.0.1',port))
    except OSError as exc:
        raise ValueError(f'{port}번 포트를 사용할 수 없습니다. --port로 다른 포트를 지정하세요.') from exc


def wait_ready(process,origin,timeout=30):
    deadline=time.monotonic()+timeout
    with httpx.Client(timeout=1,trust_env=False) as client:
        while time.monotonic()<deadline:
            if process.poll() is not None: raise ValueError('서버 실행에 실패했습니다. 위 오류 내용을 확인하세요.')
            try:
                response=client.get(origin+'/health')
                if response.status_code==200 and response.json()=={'status':'ok'}:
                    if process.poll() is not None: raise ValueError('서버가 종료되었습니다.')
                    return
            except (httpx.HTTPError,ValueError):pass
            time.sleep(.2)
    raise ValueError('서버 시작을 확인하지 못했습니다. 위 오류 내용을 확인하세요.')


def show_platform(origin,no_browser=False):
    print('\nInvestPilot 플랫폼 준비 완료',flush=True)
    print('플랫폼: '+origin+'/',flush=True)
    print('로그인: '+origin+'/login',flush=True)
    print('예측 비교: '+origin+'/lab/comparison',flush=True)
    print('종료하려면 이 터미널에서 Ctrl+C를 누르세요.\n',flush=True)
    if not no_browser:
        try: opened=webbrowser.open(origin+'/login',new=2)
        except webbrowser.Error:opened=False
        if not opened:print('브라우저를 열지 못했습니다. 위 플랫폼 주소를 브라우저에 입력하세요.',flush=True)


def main():
    parser=argparse.ArgumentParser(description='InvestPilot 플랫폼 실행')
    parser.add_argument('--port',type=int,default=8000)
    parser.add_argument('--no-browser',action='store_true',help='주소만 출력하고 브라우저를 열지 않음')
    args=parser.parse_args()
    if not 1<=args.port<=65535:parser.error('port는 1~65535 범위여야 합니다.')
    os.chdir(ROOT);load_dotenv(ROOT/'.env')
    process=None
    def shutdown(signum, frame): raise KeyboardInterrupt
    previous_handler=signal.signal(signal.SIGTERM,shutdown)
    try:
        settings=AuthSettings.environment()
        ensure_port(args.port)
        if settings.enabled:ensure_owner(AuthStore(os.getenv('INVESTPILOT_AUTH_DB','data/auth.db')))
        environment=launch_environment(os.environ)
        public=settings.public_origin
        if public and urlsplit(public).hostname in ('localhost','127.0.0.1','::1') and public!=local_url(args.port):
            raise ValueError('로컬 PUBLIC_ORIGIN은 실행 주소 '+local_url(args.port)+'와 일치해야 합니다.')
        process=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(args.port)],
                                 cwd=ROOT,env=environment)
        wait_ready(process,local_url(args.port))
        show_platform(public or local_url(args.port),args.no_browser)
        return process.wait()
    except ValueError as exc:
        print(str(exc),file=sys.stderr);return 1
    except KeyboardInterrupt:return 0
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait()
        signal.signal(signal.SIGTERM,previous_handler)


if __name__=='__main__':raise SystemExit(main())
