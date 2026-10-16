# 주가·뉴스 자동 수집과 Drive 보관

기존 웹 서버에서 선택적으로 실행하는 공개 연구 데이터 수집기다. 국내 지정 종목의 과거 일봉을 정기 갱신하고 RSS 뉴스 제목·링크·발행일을 모은다. 실계좌·포트폴리오·주문·OpenAI·Ollama 호출 및 모델 학습은 수행하지 않는다. MCP에서 수집을 시작하는 도구도 추가하지 않는다.

## 승인 후 설정

기본값은 비활성이며 이 PR은 운영 활성화 승인이 아니다. 기존 DB 연결값과 암호화 키를 변경하지 않는다.

| 환경변수 | 용도 |
|---|---|
| INVESTPILOT_COLLECTION_ENABLED | true일 때 웹 시작과 함께 수집 루프 실행, 기본 false |
| INVESTPILOT_COLLECTION_SYMBOLS | 국내 6자리 종목 코드, 쉼표 구분, 최대 50개. 기본 빈 목록 |
| INVESTPILOT_COLLECTION_PRICE_SECONDS | 일봉 재조회 간격, 기본 86400초, 최소 3600초 |
| NEWS_RSS_URLS | 기존 설정 재사용, 최대 20개. 기본 빈 목록 |
| NEWS_POLL_SECONDS | 뉴스 간격, 기본 300초, 최소 60초 |
| INVESTPILOT_COLLECTION_DRIVE_ENABLED | true일 때 Drive 자동 업로드, 기본 false |
| MODEL_LAB_STORAGE_CONFIG | 기존 비공개 Drive 폴더·저장 정책 파일 경로 |
| GOOGLE_DRIVE_ACCESS_TOKEN | 기존 단기 토큰 방식. 만료 후 수동 교체 필요 |
| GOOGLE_DRIVE_REFRESH_TOKEN | 장기 자동화를 위한 사용자가 승인한 refresh token |
| GOOGLE_DRIVE_CLIENT_ID / GOOGLE_DRIVE_CLIENT_SECRET | refresh token을 발급한 OAuth 앱의 기존 인증정보 |

refresh token이 설정되면 고정 Google 토큰 주소에서 access token을 갱신하고 메모리에 캐시한다. 토큰·인증정보는 로그·DB·수집 파일에 저장하지 않는다. 새 OAuth 앱이나 토큰 발급은 이 작업에서 수행하지 않았다. 기존 Google Drive CLI도 refresh token 방식을 지원한다. Google 연결을 ChatGPT에 추가한 것만으로 서버 토큰이 제공되지는 않는다.

## 저장·재시도·중복 방지

- SQLite는 data/collection.db, PostgreSQL은 investpilot_collection 스키마를 사용한다. Render에서 활성화하려면 INVESTPILOT_DATABASE_URL이 필요하며 메모리·로컬 파일로 대체하지 않는다. 실제 DB 영속성과 용량은 운영에서 별도 확인한다.
- 수집 직후 정규화 JSON을 gzip·base64로 DB에 저장한다. 일봉에는 원본 응답과 SHA-256도 포함한다. 뉴스는 비공개 RSS 주소가 들어갈 수 있는 원문을 저장하지 않고 정규화 기사만 보존한다.
- 종목·뉴스별 다음 실행 시각, 마지막 성공, 실패 횟수와 고정 오류 코드를 저장한다. 실패 시 60초부터 최대 1시간까지 지수 백오프한다. HTTP 재시도를 한 요청 안에서 무제한 수행하지 않는다.
- 작업 lease를 트랜잭션으로 획득한다. 강제 종료 후 미완료 lease는 최대 1시간 뒤 재시도한다. 동일 DB를 쓰는 웹 프로세스와 CLI도 중복 실행을 억제한다.
- 일봉은 매번 최신 응답을 받아 갱신한다. 한국 시각 15:30 이전의 당일 봉과 미래 봉은 제외하고 OHLC·중복 날짜를 검사한다. 거래소 휴장일·수정주가·기업행위까지 독립 검증한 자료는 아니다. 네이버 공개 차트 경로는 형식·제공 여부가 바뀔 수 있다. 미국 데이터와 현재 시총 상위50 자동 선정은 포함하지 않으며 운영자가 종목 목록을 지정한다.
- 같은 수집물은 내용 해시로 중복 저장하지 않는다. 뉴스는 순서를 정렬하고 RSS 자체 생성 시각 변경만으로 중복 보관하지 않는다.
- 업로드 대기 DB는 base64 기준 32MB·메타데이터 최대 10000건으로 제한한다. 초과하면 새 저장을 실패 처리하고 대기 데이터를 몰래 삭제하지 않는다. 승인된 Drive 업로드가 끝난 오래된 메타데이터만 정리한다.
- 매 루프 최대 3개 파일을 Drive에 업로드한다. 기존 5GB 정책·예비 0.75GB·분류별 한도·Google 계정 잔여 공간 검사를 재사용한다. Drive 파일의 내용 해시 appProperties를 검색해, 업로드 응답 후 DB 기록 전에 중단된 경우의 재전송을 중복 처리하지 않도록 한다.
- Drive 성공 응답을 DB에 기록한 뒤 DB의 압축 본문을 비운다. 이후 원본 데이터는 Drive에 있고 DB에는 이력만 남는다. Google 파일을 자동 삭제·교체하지 않는다. Drive의 자료를 다시 내려받아 학습시키는 작업은 별도 단계다.
- 업로드 실패·토큰 만료·용량 초과 시 DB 대기 자료를 보존하고 재시도한다. 장기간 실패하면 DB 상한에 도달해 추가 수집이 멈출 수 있다. 수동 CLI 업로드와 다른 프로그램이 동시에 같은 Drive 공간을 쓰면 단일 작업의 사용량 검사로 원격 전체의 동시 증가를 완전히 막을 수 없다.

## 실행·확인

웹 시작 명령은 기존 python -m scripts.deploy 그대로다. 자동 수집이 활성화되면 기존 RSS 단독 루프 대신 통합 수집 루프가 뉴스를 받아 기존 뉴스 DB에도 반영하므로 동일 서버 내 이중 RSS 폴링을 하지 않는다. 기존 실시간 토스 스트리밍과는 별개다.

```bash
python -m scripts.collect_data status
python -m scripts.collect_data once
python -m scripts.collect_data run
```

CLI는 신뢰하는 서버에서 사용한다. once는 실행 예정 시각이 지난 작업만 수행하며 강제 재조회가 아니다. run은 같은 스케줄러를 계속 실행한다. 상태 확인은 실행을 시작하지 않는다. 웹에서는 로그인한 관리자만 GET /api/collection/status로 활성 여부·수집 대상 개수·작업별 마지막 성공·다음 실행·실패 횟수·대기 건수/크기를 조회한다. 비밀 URL·토큰·Drive 파일 ID를 반환하지 않는다. 수집 자료는 운영자 공용 연구 자료이며 사용자별 실계좌 자료는 포함하지 않는다.

서버가 꺼지거나 호스팅이 중지·휴면 상태가 되면 루프도 실행되지 않는다. 인프로세스 수집만으로 24시간 실행을 보장하지 않으며 서버가 다시 시작되면 저장된 일정에 따라 재개한다. 외부 스케줄러·유료 상시 실행 서비스 생성이나 호스팅 변경은 하지 않았다.

## 검증 범위

모의 응답으로 수집·중복 제거·예정 시각·백오프·크기 제한·오류 비밀값 제외·업로드 실패 보존·Drive 중복 조회·OAuth 갱신 캐시·관리자 상태 권한을 검사한다. 임시 PostgreSQL에서 재시작 후 데이터 보존과 동시 lease를 검사한다. 실제 공개 데이터 수집·Google OAuth 발급·Drive 업로드·운영 활성화 성공은 별도 확인 대상이다. PR #19의 MCP 통합과 독립된 dev 기반 기능이다.
