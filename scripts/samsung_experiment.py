"""Offline Samsung daily-price experiment. Stores artifacts only under data/."""
import argparse
import hashlib
import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import httpx
from app.experiments.training import parse_naver,train_experiment

SOURCE='https://fchart.stock.naver.com/sise.nhn?symbol=005930&timeframe=day&count=1500&requestType=0'

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source-xml',help='Reuse a previously downloaded original XML')
    parser.add_argument('--output',default='data/experiments/samsung-price-v1')
    args=parser.parse_args()
    if args.source_xml:body=Path(args.source_xml).read_bytes()
    else:
        with httpx.Client(timeout=30,follow_redirects=True,trust_env=False) as c:
            r=c.get(SOURCE);r.raise_for_status();body=r.content
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    (output/'source.xml').write_bytes(body)
    df=parse_naver(body)
    df.to_csv(output/'prices.csv',index=False)
    report=train_experiment(df,output,hashlib.sha256(body).hexdigest(),SOURCE)
    summary=['# 삼성전자 가격 기준 모델 실험','',f"데이터: {report['start']} ~ {report['end']} ({report['rows']}개 일봉)",'',
        '| 예측 기간 | 정확도 | 기준 정확도 | Log loss | 기준 Log loss | 기준 개선 |','|---|---:|---:|---:|---:|---|']
    for e in report['experiments']:
        summary.append(f"| {e['horizon_trading_days']}거래일 | {e['accuracy']:.1%} | {e['baseline_accuracy']:.1%} | {e['log_loss']:.4f} | {e['baseline_log_loss']:.4f} | {'예' if e['beats_baseline_log_loss'] else '아니오'} |")
    summary+=['','Log loss는 낮을수록 좋습니다. 기준 모델은 학습 구간 결과 빈도를 모든 평가일에 동일하게 예측합니다.',
        '상승: +1% 초과 / 하락: -1% 미만 / 횡보: 그 사이. 학습 60%·보정 20%·평가 20%를 시간순으로 분할하며 라벨 경계 겹침을 제외했습니다.',
        '',*['- '+v for v in report['limitations']], '', '이 결과는 실험용이며 매매에 자동 적용되지 않습니다.']
    (output/'summary.md').write_text('\n'.join(summary)+'\n')
    print(json.dumps({'rows':report['rows'],'start':report['start'],'end':report['end'],'results':[{k:e[k] for k in ['horizon_trading_days','accuracy','baseline_accuracy','log_loss','baseline_log_loss','beats_baseline_log_loss']} for e in report['experiments']]},ensure_ascii=False))

if __name__=='__main__':main()
