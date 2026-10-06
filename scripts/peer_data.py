"""Collect completed peer daily bars for the isolated Samsung AI experiment."""
import argparse
import hashlib
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
import httpx
from app.experiments.training import parse_naver
from app.experiments.ai_api import PEERS

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source-dir',help='Optional directory containing peer_<symbol>.xml')
    parser.add_argument('--output',default='data/experiments/samsung-price-v1')
    args=parser.parse_args();out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    sources=[]
    for symbol,name in PEERS.items():
        url=f'https://fchart.stock.naver.com/sise.nhn?symbol={symbol}&timeframe=day&count=1500&requestType=0'
        if args.source_dir:body=(Path(args.source_dir)/f'peer_{symbol}.xml').read_bytes()
        else:
            with httpx.Client(timeout=30,trust_env=False) as c:
                r=c.get(url);r.raise_for_status();body=r.content
        df=parse_naver(body)
        (out/f'peer_{symbol}.xml').write_bytes(body)
        df.to_csv(out/f'peer_{symbol}.csv',index=False)
        sources.append({'symbol':symbol,'name':name,'rows':len(df),'start':df.date.iloc[0],'end':df.date.iloc[-1],
            'source_url':url,'sha256':hashlib.sha256(body).hexdigest()})
    manifest={'created_at':datetime.now(ZoneInfo('Asia/Seoul')).isoformat(),'sources':sources,'usage':'AI paper experiment context only, no model retraining'}
    (out/'peer_sources.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(manifest,ensure_ascii=False))

if __name__=='__main__':main()
