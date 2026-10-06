# InvestPilot

뉴스와 투자 현황을 함께 보는 로컬 투자 도구. **v0.2.0은 가상매매 + 토스 조회 전용**입니다.
RSS 자동 수집, OpenAI 제목 분석, 토스 계좌/보유종목 조회와 국내 WebSocket 체결 시세 어댑터를 제공합니다.
실제 주문 기능은 없으며 실계좌 잔고는 가상매매 잔고와 별도로 표시합니다.
외부 서비스는 로컬 인증/설정 후 실행됩니다. 실계좌·LLM 실제 접속은 개발 환경에서 검증하지 않았습니다.

## Windows 실행 (Python 3.11 이상)

```powershell
git clone https://github.com/wjdwodhks35/InvestPilot.git
cd InvestPilot
git switch feat/invest-pilot-v1
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

또는 저장소 폴더에서 `powershell -ExecutionPolicy Bypass -File .\run.ps1`로 설치와 실행을 한 번에 진행합니다.

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
가상매매 규칙은 **수동 가격 갱신 시** 평가되며, 규칙 저장만으로 평가되지 않습니다.
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

- 실제 로컬 인증 후 토스 조회/시세 및 OpenAI 접속 검증
- 기사 본문/공시 연계, 사건 단위 중복 제거, 자동 분석 비용 한도
- 실시간 시세를 가상매매에 연결하기 위한 등락률·시장 세션 확인
- 수익률 이력과 React 대시보드
- 수수료, 주문/체결 상태 동기화, 장애 복구, 일일 손실 제한 후 소액 실주문

## 로컬 연결 설정

프로젝트 루트에서 `.env.example`을 `.env`로 복사하고 필요한 항목을 설정합니다. 재시작 후 반영됩니다.
키를 채팅이나 GitHub에 올리지 마세요. `.env`는 Git에서 제외됩니다.

```powershell
Copy-Item .env.example .env
```

- `NEWS_RSS_URLS`: 본인이 선택한 RSS/Atom URL을 쉼표로 구분합니다. 기본은 미설정이며 서버 시작 즉시 및 기본 300초 간격으로 수집합니다.
- `NEWS_POLL_SECONDS`: 수집 주기(최소 60초). 수집 실패는 화면에 건수로 표시하고 다음 주기에 재시도합니다.
- `OPENAI_API_KEY`, `OPENAI_MODEL`: Responses API 및 JSON Schema 구조화 출력을 지원하는 모델을 설정합니다. 뉴스별 **AI 제목 분석** 버튼을 누를 때만 호출되며 API 사용료가 발생합니다. ChatGPT 구독과 API 사용료는 별개입니다.
- `TOSS_CLIENT_ID`, `TOSS_CLIENT_SECRET`: 토스에서 발급한 Client Credentials입니다. 과거 예제의 APP_KEY 이름 대신 공식 스펙에 맞춘 CLIENT_ID를 사용합니다.
- `TOSS_ACCOUNT_SEQ`: `/api/broker/accounts`에서 확인한 `account_seq`를 설정합니다. 계좌번호 원문은 해당 API에서 반환하지 않습니다.
- `TOSS_STREAM_ENABLED=true`: 서버 시작 시 관심종목의 국내 체결 시세를 구독합니다. 기본 false.

토스 REST/WebSocket 모두 토스 WTS의 **Open API → 허용 IP 관리**에 로컬 PC가 사용하는 공인 IP 등록이 필요합니다.
토큰은 메모리에만 보관하고 만료 전에 재발급합니다. 같은 Client ID로 다른 프로그램에서 토큰을 재발급하면 기존 토큰이 무효화될 수 있습니다.
WebSocket은 60초마다 PING을 보내며 연결 종료 시 최대 60초 지수 백오프로 재연결합니다.
구독 직후 초기 스냅샷은 제공되지 않으므로 체결이 발생할 때부터 데이터가 쌓입니다. 시장이 닫혀 있으면 그래프가 비어 있을 수 있습니다.
토스 체결 가격은 **가상매매 주문에 사용되지 않습니다**. 당일 등락률·시장 세션·수수료 검증을 마친 뒤 가격 공급원 통합을 진행합니다.
가격 그래프의 가로축은 관측 순서입니다. 수동 입력과 토스 체결 이력을 선택할 수 있습니다.

RSS는 URL(프래그먼트 제외)로 중복 제거합니다. 서로 다른 URL의 동일 사건은 아직 합치지 않습니다.
뉴스 발행일을 알 수 없으면 미상으로 표시합니다. AI 분석은 기사 본문이 아닌 제목만 근거로 합니다.
RSS 수집 URL은 운영자가 `.env`에 설정하며 웹 API로 임의 URL을 서버에서 가져오는 기능은 제공하지 않습니다.
단일 서버 프로세스로 실행하세요. 여러 worker/process에서 주문 평가를 공유하는 구성은 지원하지 않습니다.

## 공식 스펙 및 검증 범위

- REST: https://openapi.tossinvest.com/openapi-docs/latest/openapi.json
- WebSocket: https://openapi.tossinvest.com/openapi-docs/latest/asyncapi.json
- 인증: `POST /oauth2/token`, form-urlencoded Client Credentials
- 조회: `GET /api/v1/accounts`, `GET /api/v1/holdings` + `X-Tossinvest-Account`
- 시세: `wss://openapi-ws.tossinvest.com/ws/v1`, 선언형 `trade:kr` 구독
- LLM: https://developers.openai.com/api/docs/guides/structured-outputs

외부 어댑터는 공식 스펙 기반 모의 응답으로 테스트했습니다. 실제 API 인증키와 허용 IP가 없으므로 실제 서버와의 통합 검증은 별도입니다.

## 별도 테스트 기능: 모델 실험실

`/lab`은 과거 데이터 학습·검증 전용 공간이며 투자 대시보드와 별도 페이지/API입니다.
현재는 CSV 데이터 검사만 지원합니다. 학습·확률 추정은 아직 미구현입니다.
뉴스 발행시각이 판단 시각보다 늦거나 시간대가 없으면 거부합니다. 종목별 시간 정렬, 중복, 가격/거래량 유효성을 검사합니다.
검사 데이터는 저장되지 않으며 주문 엔진·실계좌·가상 잔고를 변경하지 않습니다.
실험 코드는 `app/experiments/`, API는 `/api/experiments/*`에 분리돼 있습니다.
