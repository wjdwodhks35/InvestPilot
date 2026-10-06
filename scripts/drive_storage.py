"""Run: python -m scripts.drive_storage usage | upload CATEGORY FILE
Requires a local Google OAuth access token with Drive read/write access.
ChatGPT's Google connection is not automatically available to a local server.
"""
import argparse
import json
import os
import sys
from dotenv import load_dotenv
from app.experiments.storage import DriveStorage


def main():
    load_dotenv()
    parser=argparse.ArgumentParser(description='InvestPilot research Drive storage')
    commands=parser.add_subparsers(dest='command',required=True)
    commands.add_parser('usage')
    upload=commands.add_parser('upload')
    upload.add_argument('category',choices=['prices','news','features','models','reports'])
    upload.add_argument('file')
    args=parser.parse_args()
    if not os.getenv('GOOGLE_DRIVE_ACCESS_TOKEN'):
        parser.error('GOOGLE_DRIVE_ACCESS_TOKEN을 로컬 .env에 설정하세요 (채팅에 보내지 마세요)')
    storage=DriveStorage()
    try:
        result=storage.usage() if args.command=='usage' else storage.upload(args.file,args.category)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except Exception as exc:
        # HTTP errors can contain details about account data; do not echo response bodies or tokens.
        print(str(exc) if isinstance(exc,ValueError) else type(exc).__name__+' — Drive 인증/연결 확인 필요',file=sys.stderr)
        return 1
    finally:storage.client.close()
    return 0

if __name__=='__main__':raise SystemExit(main())
