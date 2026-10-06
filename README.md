# InvestPilot

뉴스와 투자 현황을 함께 보는 로컬 투자 도구. **v0.1.0은 가상매매 전용**입니다.
실제 토스 계좌, 실시간 시세, 자동 뉴스 수집, LLM은 아직 연결되지 않았습니다.
뉴스는 수동 등록 후 키워드로 분류하며 AI 추천으로 표시하지 않습니다.

## Windows 실행 (Python 3.11 이상)

```powershell
git clone https://github.com/wjdwodhks35/InvestPilot.git
cd InvestPilot
git switch feat/invest-pilot-v1
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

http://127.0.0.1:8000 에서 대시보드, `/docs`에서 API 문서를 확인합니다.
PC에서 실행하기 전까지 이 프로그램이 백그라운드로 감시하지는 않습니다.

## 기능과 테스트 방법

1. 초기 가상 현금 100만원. 관심종목에서 안랩을 골라 현재가 `10000`, 등락률 `0`을 입력합니다.
2. 60초 내 5주 가상매수합니다. 현금 95만원, 보유 5주가 됩니다.
3. 가격을 `9000`으로 갱신하면 기본 손절 7% 규칙에 의해 5주 가상매도됩니다.
4. 매매 규칙에서 목표수익률, 손절, 트레일링 활성 조건, 주문당/일일 매수 한도, 급등 차단을 변경합니다.
5. 긴급 정지는 수동 주문과 규칙 자동 주문을 모두 차단합니다.
6. 뉴스 제목을 등록하면 관련 회사와 중요 키워드를 표시합니다. 뉴스는 주문을 발생시키지 않습니다.

가상 주문은 입력 가격에서 전량 체결된다고 가정합니다. 수수료·세금·호가·슬리피지는 반영하지 않습니다.
규칙은 **가격 갱신 시** 평가되며, 규칙 저장만으로 평가되지 않습니다.
현재 지원 통화는 KRW, 종목은 국내 6자리 코드입니다. 미국 종목과 환율 처리는 후속 범위입니다.
일일 매수금액 한도는 한국 날짜를 기준으로 집계합니다. 요청 ID로 중복 주문을 방지합니다.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 구조

- `app/engine.py`: SQLite 상태, 가상 주문, 리스크 규칙, 키워드 뉴스 분류
- `app/main.py`: FastAPI 및 입력 검증
- `app/static/index.html`: 빌드 없이 실행되는 웹 대시보드
- `tests/`: 잔고, 중복 주문, 손절/익절/트레일링, 한도, 오래된 가격 검증
- `.github/workflows/tests.yml`: push/PR 시 자동 테스트

데이터는 `data/investpilot.db`에 저장됩니다. 종료 후에도 유지됩니다.
`INVESTPILOT_DB` 환경변수로 DB 경로를 지정할 수 있습니다.
`.env`, 계좌 데이터, DB는 Git에서 제외합니다. `.env.example`은 후속 연동용 자리표시자이며 V1은 읽지 않습니다.
서버에는 인증 기능이 없으므로 기본 실행 주소 `127.0.0.1`을 사용하세요.

## 다음 개발 단계

- 공식 토스 API 스펙 확인 후 계좌 조회 및 WebSocket 시세 어댑터
- 출처·발행시각·중복 제거를 갖춘 뉴스/RSS 수집과 LLM 구조화 분석
- 가격 이력·수익률 그래프와 React 대시보드
- 수수료, 주문/체결 상태 동기화, 장애 복구, 일일 손실 제한 후 소액 실주문

공식 참조: https://developers.tossinvest.com/docs 및 https://developers.tossinvest.com/docs/market-data
실주문 API 경로·인증 필드는 검증 전 임의로 구현하지 않습니다.
