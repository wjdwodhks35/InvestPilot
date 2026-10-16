# ChatGPT 읽기 전용 포트폴리오 MCP

ChatGPT가 기존 InvestPilot 사용자별 토스 연결로 포트폴리오를 조회하고 ChatGPT 안에서 분석한다. 새 MCP 기능은 OpenAI API를 호출하지 않으며 OpenAI API 키가 필요하지 않다. 기존 내부 분석 기능의 별도 API 사용 여부와 ChatGPT 요금제·연결 기능 제공 여부는 별개다.

## 웹 서버 통합

- `app.main:app`에 선택적으로 통합한다. Render의 기존 설치 명령 `pip install -r requirements.txt`와 시작 명령 `python -m scripts.deploy`를 유지한다. 기본값은 비활성이다.
- 공식 MCP Python SDK 1.26.0의 stateless Streamable HTTP를 사용한다. 주 앱의 lifespan이 MCP 세션 관리자를 시작하고 종료한다. 웹 작업 정리 후 MCP가 종료되며 시작 실패 시에도 자원을 정리한다.
- 가장 바깥의 `MCPDispatch`가 정확히 `/mcp`와 `/.well-known/oauth-protected-resource/mcp`만 MCP로 전달한다. `/mcp/`, 하위 경로, 기존 API에는 기존 웹 인증이 적용된다. MCP 경로의 WebSocket은 거부한다.
- MCP는 쿠키 인증·계정 실험 미들웨어를 통과하지 않는다. 웹 쿠키로 MCP에 접근할 수 없고, MCP bearer 토큰으로 웹 관리·설정·주문 API에 접근할 수 없다. MCP를 웹의 공개 경로 목록에 추가하지 않는다.
- 기존 `AuthStore`와 `BrokerAccounts` 인스턴스를 주입하여 사용자 연결·제한·저장 설정·broker·잠금을 공유한다. MCP로 처음 접근하는 사용자는 paper engine·실험 객체·연구 작업을 생성하지 않는다. 이후 일반 웹 broker 접근은 동일 객체에 기존 계정 engine을 연결한다.
- 기존 웹 서버 시작 시 수행하던 작업은 유지한다. MCP 요청은 실험·백그라운드 연구를 시작하지 않는다.
- 별도 실행 `uvicorn app.mcp_server:create_app --factory`는 호환용으로 남겨 두지만 현재 권장 운영 경로는 기존 웹 서버 통합이다. `requirements-mcp.txt`는 기존 설치 호환용 파일이다.

## 인증과 데이터 경계

- JWT는 RS256 서명, 고정 HTTPS JWKS, issuer, audience, 만료·발급 시각, subject, `portfolio:read`, 허용 Client ID를 검증한다. 미연결 사용자는 거부하며 owner 기본값이나 이메일 자동 연결을 사용하지 않는다.
- 기존 인증 DB의 영구 연결과 호출 제한을 재사용한다. SQLite와 PostgreSQL을 지원하며 연결 해제 후 다음 요청은 거부된다.
- 도구는 `get_portfolio`, `get_portfolio_breakdown` 두 개뿐이다. 인수·주문·관리·설정·모델 호출 도구는 없다.
- 반환 데이터는 종목 코드·수량·가격·통화별 합계·조회 시각으로 제한한다. 계좌번호, 비밀키, 종목명과 임의 설명문을 제외한다. 조회 시각은 시세 시각이 아니며 서로 다른 통화를 합산하지 않는다.
- 요청 32 KiB, broker 응답 2 MB, 보유 항목 200개, 고정 timeout·재시도 없음, 사용자별 인증 요청 20회/분·500회/일 및 전역 제한을 적용한다. 인증 요청은 gateway와 검증 단계에서 전역 제한을 두 번 차감한다.
- 기존 암호화 키와 DB 연결값을 유지한다. 새 사용자 DB나 새 키로 기존 설정을 대체하지 않는다.

## 승인 후 활성화할 설정

새 서비스 추가는 필요하지 않다. 아래 설정은 아직 운영에 적용하지 않았다.

- `INVESTPILOT_MCP_ENABLED=true` (기본 `false`; 잘못된 값은 시작 실패)
- `INVESTPILOT_MCP_ISSUER`: OAuth 제공자의 정확한 HTTPS issuer
- `INVESTPILOT_MCP_JWKS_URL`: 신뢰하는 고정 HTTPS JWKS URL
- `INVESTPILOT_MCP_RESOURCE`: 기존 `INVESTPILOT_PUBLIC_ORIGIN`에 `/mcp`를 붙인 정확한 주소
- `INVESTPILOT_MCP_CLIENT_IDS`: 허용 OAuth Client ID 목록, 쉼표 구분
- 웹 인증과 Secure 쿠키가 모두 활성화되어 있어야 한다.

기존 DB·토스 설정·`INVESTPILOT_SETTINGS_KEY`는 변경하지 않는다. Render 무료 파일시스템의 SQLite를 영속 DB로 간주하지 않는다. 실제 운영 DB 위치와 영속성은 별도로 확인해야 한다.

## OAuth와 사용자 동의

Authorization Code + PKCE S256, resource audience 및 ChatGPT가 요구하는 클라이언트 등록 방식을 지원하는 OAuth 제공자가 필요하다. 실제 제공자 생성·등록·호환성 검증은 미완료다. 제공자 discovery와 ChatGPT가 제시하는 정확한 redirect URI를 확인하고 `portfolio:read`만 부여한다. 토스 비밀키를 OAuth 제공자나 ChatGPT에 전달하지 않는다.

운영자는 OAuth subject 소유권과 해당 InvestPilot 사용자의 명시적 동의를 확인한 뒤 신뢰하는 서버에서 연결한다. 이메일만으로 연결하지 않는다. 현재 self-service OAuth callback이나 연결 UI는 없다.

```bash
python -m scripts.mcp_access link --username <existing-user> --subject <verified-provider-subject> --consent-confirmed
python -m scripts.mcp_access revoke --username <existing-user>
```

subject와 자격증명은 공개 이슈·로그·공유 명령 기록에 남기지 않는다. 연결 키는 해시로 저장하며 bearer 토큰은 저장하지 않는다.

## 운영 확인 기록과 남은 검증

2026-10-15 읽기 전용 Render 조회 결과: 기존 `investpilot` 서비스는 무료 1개, Ohio, `dev`의 `b88b9b4f1f6fa42f6446db8346f167e3067d894c` 배포가 `live`였다. 실제 설정은 `dev` commit 자동 배포이며, 저장소 render.yaml의 Singapore·checksPass 선언과 달랐다. 운영 설정은 변경하지 않았다. 이 기록은 이후 변경될 수 있다.

이 Cloud Work에서는 로컬 Git·Python 실행이 가능하다. 별도 Linux 서버·SSH·Docker·Nginx 구축은 확인하지 않았다. CI PostgreSQL 컨테이너는 운영 DB가 아니다.

모의 응답 테스트로 SDK initialize/list/call, 인증 실패, 사용자 격리·해제, 웹 API와 bearer 격리, 공유 broker 설정, MCP 요청의 연구 작업 미생성 및 주 앱 시작·종료를 검증한다. 실제 OAuth·토스·ChatGPT 연결 성공을 뜻하지 않는다.

남은 순서: 테스트 결과 검토 → 사용자 승인 후 PR 병합·배포 → OAuth 등록 및 검증된 사용자 연결 → 실제 ChatGPT에서 discovery·동의·도구 호출·사용자 격리·해제 검증. Render는 현재 dev 커밋 자동 배포이므로 병합 승인 시 배포 영향도 함께 확인해야 한다. 사용자 승인 없이 병합·배포·실거래·비밀키 변경을 수행하지 않는다. AGENTS.md의 자동 병합 문구보다 이 제한이 우선한다.


## 비밀값을 출력하지 않는 오프라인 사전 점검

승인된 활성화를 준비할 때 기존 서비스의 환경에서 다음 명령으로 누락을 확인할 수 있다.

```bash
python -m scripts.check_mcp
```

이 명령은 현재 프로세스 환경만 읽으며 `.env`를 자동 탐색하지 않는다. 앱을 시작하거나 DB에 접속·스키마 생성·계정 연결·키 생성·외부 요청을 하지 않는다. 주소·토큰·DB 연결값·키의 원문을 출력하지 않고 고정된 점검 이름과 결과만 JSON으로 반환한다. 모든 형식 점검을 통과하면 종료 코드 0, 누락·불일치는 1이다. 준비 단계의 MCP 비활성도 미준비로 표시되며, 결과를 통과시키기 위해 승인 없이 활성화해서는 안 된다.

`configuration_ready=true`는 환경 설정 형식 점검 통과일 뿐이다. `live_connection_verified`는 항상 false이며 실제 DB 영속성, 기존 키와 저장 데이터의 일치, OAuth discovery·PKCE·등록, 본인 연결·동의 및 ChatGPT 실환경 검증을 대체하지 않는다. 이 Cloud Work의 환경 점검 결과를 Render 운영 설정 결과로 간주하지 않는다.

2026-10-16 비인증 HTTP 점검에서 운영 `/health`는 200이었고 `/mcp`와 리소스 메타데이터 주소는 로그인으로 리디렉션됐다. 최종 로그인 페이지의 200을 MCP 성공으로 해석하지 않았다. Render의 최신 live 커밋은 여전히 `b88b9b4…`였으며 통합 PR #19는 미병합 상태였다. 운영 DB 연결값·비밀값은 조회하지 않았다.
