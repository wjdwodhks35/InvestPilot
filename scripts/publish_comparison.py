"""Copy existing historical results into the external DB for free hosting."""
import argparse
from pathlib import Path
from dotenv import load_dotenv
from app.experiments.comparison import snapshot
from app.experiments.cloud_results import publish


def main():
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path('data/experiments/top50-v1'))
    args = parser.parse_args()
    result = snapshot(args.root)
    publish(result)
    print(f"예측 비교 결과 동기화: {result['completed_stocks']}/{result['total_stocks']} 종목")


if __name__ == '__main__': main()
