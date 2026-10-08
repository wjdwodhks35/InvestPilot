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
from pydantic import ValidationError

class RemoteWallet:
    def __init__(self,state):self.value=state
    def state(self,*args):return self.value

def http_failure_message(exc):
    path=exc.request.url.path
    code=exc.response.status_code
    if path=='/api/experiments/us/worker-context' and code==409:
        return '미국 모의투자 준비 상태와 최신 엔비디아 시세·유효 환율을 확인하세요 (HTTP 409). /lab/us에서 준비하기를 누르세요.'
    if path=='/api/experiments/ai/worker-context' and code==409:
        return '최신 시세 없음 (HTTP 409): 60초 이내 삼성전자 토스 시세가 필요합니다. 장 마감·휴장 또는 시세 수신 상태를 확인하세요. 오래된 가격으로 모의 주문하지 않습니다.'
    if code==401:return '로그인 세션 인증 실패 (HTTP 401). 플랫폼 로그인 정보를 확인하세요.'
    if code==403:return '접근 거부 (HTTP 403). 플랫폼 요청 권한 또는 설정을 확인하세요.'
    if path=='/api/market/refresh':return f'토스 시세 조회 요청 실패 (HTTP {code}). 플랫폼 설정에서 토스 연결 상태를 확인하세요.'
    return f'요청 실패 (HTTP {code}, {path}). 모의 주문을 실행하지 않았습니다.'

async def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--url',default='https://investpilot-iw76.onrender.com')
    parser.add_argument('--username',required=True)
    parser.add_argument('--market',choices=['kr','us'],default='kr',help='US uses isolated NVDA paper wallet')
    parser.add_argument('--export',action='store_true',help='Export your observation and decision data; does not train Ollama')
    args=parser.parse_args();origin=args.url.rstrip('/');parsed=urlsplit(origin)
    if parsed.scheme!='https' or parsed.username or parsed.password or parsed.query or parsed.fragment:
        parser.error('HTTPS platform origin required')
    password=getpass.getpass('플랫폼 로그인 비밀번호: ')
    try:
        async with httpx.AsyncClient(base_url=origin,timeout=150,trust_env=False,follow_redirects=False,headers={'Origin':origin}) as server:
            print('[1/4] 플랫폼 로그인 확인 중…',flush=True)
            r=await server.post('/api/auth/login',json={'username':args.username,'password':password});password='';r.raise_for_status()
            if args.export and args.market=='us':
                print('미국 실험 자료 내보내기는 아직 지원하지 않습니다. 웹 실험실에서 판단 기록을 확인하세요.');return
            if args.export:
                r=await server.get('/api/experiments/ai/learning-data');r.raise_for_status()
                output=Path('data/worker/learning-data.json');output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(r.json(),ensure_ascii=False,indent=2))
                print('저장:',output,'· 관측자료이며 모델 학습은 실행하지 않았습니다.');return
            # User explicitly starts one paper decision, never real brokerage orders.
            prefix='/api/experiments/us' if args.market=='us' else '/api/experiments/ai'
            print('[2/4] '+('엔비디아 달러 시세·환율·관련 종목' if args.market=='us' else '삼성전자 최신 시세와 참고 자료')+' 조회 중…',flush=True)
            if args.market=='kr':
                r=await server.post('/api/market/refresh',json={'symbol':'005930'});r.raise_for_status()
            r=await server.get(prefix+'/worker-context');r.raise_for_status();context=r.json()
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
            payload={'request_id':'pc-'+str(uuid.uuid4()),'model':experiment.model,'decision':decision.model_dump()}
            if args.market=='us':payload['context_id']=context['context_id']
            else:payload.update(price=snapshot.price,at=snapshot.at)
            r=await server.post(prefix+'/worker-decision',json=payload)
            if r.status_code==409:print('정지 상태 또는 가격 만료/변경입니다. 실험실에서 정지 해제 후 다시 실행하세요.');return
            r.raise_for_status();print('완료 · 실험실의 최근 AI 판단에서 결과를 확인하세요.',flush=True);print(json.dumps(r.json(),ensure_ascii=False,indent=2))
    except httpx.HTTPStatusError as exc:print(http_failure_message(exc))
    except httpx.TimeoutException:print('요청 시간이 초과됐습니다. 플랫폼 또는 PC Ollama 응답 상태를 확인하세요.')
    except httpx.RequestError:print('네트워크 연결 실패. 플랫폼과 PC Ollama의 실행 상태를 확인하세요.')
    except ValidationError:
        print('시세 검증 실패: 시각·가격 형식 또는 60초 유효기간을 확인하세요. 모의 주문을 실행하지 않았습니다.')
    except ValueError as exc:
        print(str(exc)+' · 모의 주문을 실행하지 않았습니다.')

if __name__=='__main__':asyncio.run(main())
