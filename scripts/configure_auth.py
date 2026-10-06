"""Set or replace the single owner on the server, without printing secrets."""
import argparse
import getpass
import os
from dotenv import load_dotenv
from app.auth import AuthStore


def main():
    load_dotenv()
    parser=argparse.ArgumentParser(description='InvestPilot 로그인 계정 설정')
    parser.add_argument('--username', required=True)
    parser.add_argument('--replace', action='store_true', help='기존 계정 변경 및 모든 로그인 해제')
    args=parser.parse_args()
    password=getpass.getpass('비밀번호 (12자 이상): ')
    if password != getpass.getpass('비밀번호 확인: '): raise SystemExit('비밀번호가 일치하지 않습니다.')
    try:AuthStore(os.getenv('INVESTPILOT_AUTH_DB','data/auth.db')).configure(args.username,password,args.replace)
    except ValueError as exc:raise SystemExit(str(exc)) from exc
    print('로그인 계정을 설정했습니다. 기존 로그인 세션은 해제되었습니다.')


if __name__=='__main__':main()
