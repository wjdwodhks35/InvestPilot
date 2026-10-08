"""PC-only Ollama worker: local model, authenticated Render paper wallet; no broker keys."""
import argparse
import asyncio
import getpass
import json
from pathlib import Path
from urllib.parse import urlsplit
import uuid
import httpx
from app.experiments.ai_paper import OllamaExperiment,Snapshot

class RemoteWallet:
    def __init__(self,state):self.value=state
    def state(self,*args):return self.value

async def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--url',default='https://investpilot-iw76.onrender.com')
    parser.add_argument('--username',required=True)
    parser.add_argument('--export',action='store_true',help='Export your observation and decision data; does not train Ollama')
    args=parser.parse_args();origin=args.url.rstrip('/');parsed=urlsplit(origin)
    if parsed.scheme!='https' or parsed.username or parsed.password or parsed.query or parsed.fragment:
        parser.error('HTTPS platform origin required')
    password=getpass.getpass('플랫폼 로그인 비밀번호: ')
    try:
        async with httpx.AsyncClient(base_url=origin,timeout=150,trust_env=False,follow_redirects=False,headers={'Origin':origin}) as server:
            print('[1/4] 플랫폼 로그인 확인 중…',flush=True)
            r=await server.post('/api/auth/login',json={'username':args.username,'password':password});password='';r.raise_for_status()
            if args.export:
                r=await server.get('/api/experiments/ai/learning-data');r.raise_for_status()
                output=Path('data/worker/learning-data.json');output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(r.json(),ensure_ascii=False,indent=2))
                print('저장:',output,'· 관측자료이며 모델 학습은 실행하지 않았습니다.');return
            # User explicitly starts one paper decision, never real brokerage orders.
            print('[2/4] 삼성전자 최신 시세와 참고 자료 조회 중…',flush=True)
            r=await server.post('/api/market/refresh',json={'symbol':'005930'});r.raise_for_status()
            r=await server.get('/api/experiments/ai/worker-context');r.raise_for_status();context=r.json()
            snapshot=Snapshot.model_validate(context['snapshot'])
            if context['wallet']['paused']:
                print('모의투자가 정지되어 있습니다. 실험실에서 준비하기를 누른 뒤 다시 실행하세요.');return
            print('[3/4] PC Ollama 연결 확인 및 AI 판단 중… 잠시 기다려 주세요.',flush=True)
            experiment=OllamaExperiment(RemoteWallet(context['wallet']))
            connection=await experiment.connection()
            if not connection['connected'] or not connection['installed']:
                print('PC의 Ollama 실행과 ollama pull '+experiment.model+'을 확인하세요.');return
            decision=await experiment.decide(snapshot)
            # Do not silently unpause an experiment: require explicit user control in lab.
            print('[4/4] 가상 체결과 결과 저장 중…',flush=True)
            r=await server.post('/api/experiments/ai/worker-decision',json={'request_id':'pc-'+str(uuid.uuid4()),'model':experiment.model,'price':snapshot.price,'at':snapshot.at,'decision':decision.model_dump()})
            if r.status_code==409:print('정지 상태 또는 가격 만료/변경입니다. 실험실에서 정지 해제 후 다시 실행하세요.');return
            r.raise_for_status();print('완료 · 실험실의 최근 AI 판단에서 결과를 확인하세요.',flush=True);print(json.dumps(r.json(),ensure_ascii=False,indent=2))
    except httpx.HTTPError:print('연결/인증 실패. 플랫폼·PC Ollama와 최신 토스 시세를 확인하세요.')
    except ValueError:print('가격 또는 AI 응답 검증 실패. 모의 주문을 실행하지 않았습니다.')

if __name__=='__main__':asyncio.run(main())
