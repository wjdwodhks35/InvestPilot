"""Operator CLI for the same opt-in public collector; no model or broker calls."""
import argparse
import asyncio
import json
from dotenv import load_dotenv
from app.collection import Collector


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description='공개 연구 데이터 자동 수집')
    parser.add_argument('command', choices=('once','status','run'))
    args = parser.parse_args()
    try:
        collector = Collector()
        if args.command != 'status' and not collector.enabled:
            print('자동 수집이 비활성 상태입니다. 승인된 설정 후 실행하세요.')
            return 1
        if args.command == 'run':
            asyncio.run(collector.loop())
        elif args.command == 'once':
            asyncio.run(collector.tick())
        report = collector.status()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return int(any(j['failures'] for j in report.get('jobs', [])))
    except KeyboardInterrupt:
        return 0
    except Exception:
        print('수집 설정 또는 저장소를 확인하세요. 비밀값은 표시하지 않습니다.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
