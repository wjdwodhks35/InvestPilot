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
    parser.add_argument('--add-user', action='store_true', help='기존 관리자 계정을 유지하고 별도 로그인 계정 추가')
    args=parser.parse_args()
    if args.add_user and args.replace: parser.error('--add-user와 --replace를 함께 사용할 수 없습니다.')
    password=getpass.getpass('비밀번호 (12자 이상): ')
    if password != getpass.getpass('비밀번호 확인: '): raise SystemExit('비밀번호가 일치하지 않습니다.')
    try:
        store=AuthStore(os.getenv('INVESTPILOT_AUTH_DB','data/auth.db'))
        if args.add_user: store.add_user(args.username,password)
        else: store.configure(args.username,password,args.replace)
    except ValueError as exc:raise SystemExit(str(exc)) from exc
    print('로그인 계정을 추가했습니다.' if args.add_user else '로그인 계정을 설정했습니다. 기존 로그인 세션은 해제되었습니다.')


if __name__=='__main__':main()
