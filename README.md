# Shortlist · 나의 투자 연구실

React/TypeScript + FastAPI + 별도 워커 + PostgreSQL로 만든 개인용 단기 주식 **연구·모의 투자 웹앱**입니다. 한국어 다크 UI에서 2~20 미국 거래일 기준의 규칙 후보, 근거/위험, 모의 지정가 주문과 부분 체결, 보유 추적, 재분석, 사용자 매도, 영속 기록과 가격 백테스트를 제공합니다.

**모든 기본 시세·호가·환율·시장/업종 값은 합성 데이터입니다.** 실제 시세는 KIS 읽기 어댑터가 준비됐지만 키·권한·원본 시각을 검증하지 못했습니다. 실제 주문/실증권사 대사, 실제 뉴스·공시·기업행동·시장 경보 연결과 실제 장기 전략 검증은 미완료입니다. 실주문은 환경 플래그만 켜도 실행되지 않습니다. 수익·목표일 수익 달성·손실 상한을 보장하지 않습니다.

## 빠른 시작 (Linux/macOS)

Python **3.12.14**, Node **22.22.0**, Docker Compose를 사용합니다. Python은 `uv.lock`/해시 포함 `requirements.txt`, JS는 `frontend/package-lock.json`에 고정돼 있습니다.

```bash
git clone https://github.com/alstjr81872-cpu/invest.git
cd invest
python -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.txt
.venv/bin/python -m pip install --no-deps .
# 또는 고정 잠금파일을 사용하는 uv sync --frozen
npm ci --prefix frontend
npm run build --prefix frontend
docker compose up -d --wait db
.venv/bin/python scripts/init_local.py
.venv/bin/python scripts/run_local.py
```

로컬에서 `http://127.0.0.1:8000`에 접속해 `owner`와 설정한 비밀번호로 로그인합니다. 인터넷 사용자에게 제공하는 방법은 **[Render 배포 안내](DEPLOY_RENDER.md)**입니다. 로컬 검증 주소는 실제 배포 주소가 아닙니다.

`init_local.py`는 비밀번호를 숨겨 입력받아 Argon2id 해시와 무작위 세션 키를 `.env`에 기록하며 기존 `.env`를 덮어쓰지 않습니다. `.env.example`은 이름만 있는 안내용이며 그대로 복사하면 실행되지 않습니다. 현재 환경에 `.env`가 이미 있으면 안전하게 편집하여 소유자 해시를 설정하세요. 평문 비밀번호는 저장하지 마세요. 기존 해시를 바꾼 뒤에는 웹 프로세스를 재시작해야 반영됩니다. `.env`의 해시 값은 `$`를 보존하기 위해 따옴표로 감쌉니다.

`run_local.py`는 마이그레이션 후 독립적인 Web/Worker 프로세스를 실행합니다. Ctrl+C로 이 두 프로세스만 종료하며 DB 볼륨은 유지합니다. 개발 서버를 따로 실행할 수도 있습니다.

```bash
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m invest.worker
# 다른 터미널
.venv/bin/python -m uvicorn invest.api:app --host 127.0.0.1 --port 8000
```

## Docker 배포

루트 `Dockerfile`을 제공합니다. 무료 배포는 Render Free Web 1개와 Neon Free DB를 사용합니다. Docker Command는 비워 두고 `FREE_TIER_MODE=true`를 설정합니다. 별도 Background Worker는 만들지 않습니다. 웹 기본 CMD는 DB 마이그레이션 후 서버를 시작합니다. [무료 배포 설정](DEPLOY_FREE.md)을 참고하세요. PostgreSQL과 환경변수는 별도로 필요합니다.

## Windows 개발 (PowerShell)

Python 3.12.14, Node 22.22.0, Docker Desktop을 설치하고 Linux 컨테이너를 활성화합니다. PowerShell 실행 정책을 바꾸지 않아도 venv Python을 직접 호출할 수 있습니다.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.txt
.\.venv\Scripts\python.exe -m pip install --no-deps .
npm ci --prefix frontend
npm run build --prefix frontend
docker compose up -d --wait db
.\.venv\Scripts\python.exe scripts\init_local.py
.\.venv\Scripts\python.exe scripts\run_local.py
```

Windows 호스트 자체에서는 아직 실행 검증하지 않았습니다. Linux/Python과 브라우저 테스트는 실행했습니다. 데이터 저장은 양쪽 모두 PostgreSQL이며 SQLite 대체 경로가 없습니다.

## 사용하는 흐름

1. **설정**에서 기간·목표 USD 순수익률·USD/KRW 예산·거래당 USD 손실 예산·최대 비중/보유수를 저장합니다. 기존 외부 보유는 선택 입력이며 모의 체결과 구분합니다. 실제 환율은 미연결이므로 데모 KRW는 고정 합성 환율입니다.
2. **추천 종목 → 후보 분석하기**에서 최대5개의 조건 통과 후보와 나머지 탈락 사유를 봅니다. 0개도 정상입니다. 점수는 규칙 적합도이고 확률이 아닙니다. 예시 설정을 검증된 전략으로 홍보하지 않습니다.
3. **상세 분석 · 모의 투자하기**에서 캔들·MA·거래량·RSI, 근거3개/위험3개, 지정가와 수량·예상 비용을 확인한 뒤 **모의 투자 주문 제출**을 누릅니다.
4. **내 투자**에서 주문접수→부분체결→전량체결/취소를 봅니다. 클릭 가격과 체결 평균가는 다릅니다. 다음 합성 호가가 지정가를 만족할 때만 최대3주/틱으로 체결합니다. 실장이 닫혀 있어도 명시된 **가상 정규장 세션**에서만 데모 체결을 시연합니다.
5. **분석하기 / 전체 분석**은 최신 시세와 완성 일봉·시장/업종을 재계산합니다. 최초·직전 판단과의 변화와 반대 근거를 보여주며 주문을 실행하지 않습니다. 미확보 뉴스·공시·분봉은 분석했다고 표시하지 않습니다.
6. **일부 / 전량 모의 매도**로 별도 매도 주문을 제출합니다. 최초 목표·손절/만료를 임의로 바꾸지 않으며 자동 손절·자동 매도는 없습니다.
7. **분석 기록**에서 보유 분석·합성 과거 실험·거래 기록을 확인합니다. 보유 분석은30초, 추천은15분 후 오래됨/유효기간 초과로 처리합니다.

**무료 모드에서는 버튼을 누를 때만 갱신하며, 주문 후 시세·체결 갱신을 눌러야 합니다. 접속하지 않으면 수집·체결·경보가 실행되지 않습니다.** 로컬 기본 모드에서는 워커가 살아 있으면 추적이 계속됩니다. WebSocket 재연결은 점진적 지연을 사용하며 DB snapshot과 이벤트 ID로 복구합니다. 서버 정지/배포 공백은 있을 수 있고 heartbeat·오래된 시세 경고를 확인해야 합니다.

## 테스트

실제 PostgreSQL 테스트 DB를 사용합니다. 이름이 `_test`로 끝나지 않으면 파괴적 테스트를 거절합니다. **테스트 DB의 모든 앱 테이블은 각 테스트마다 비웁니다. 운영 DB를 지정하지 마세요.**

```bash
docker compose exec db createdb -U invest invest_test
# 개발 의존성은 uv sync --frozen 또는 .venv에 pytest 설치
uv sync --frozen
uv run pytest -q
uv run ruff check backend
uv run alembic check
npm run build --prefix frontend
# 시스템 Chromium 사용 시; 설치되지 않았으면 playwright install chromium
docker compose exec db createdb -U invest invest_e2e_test
uv run python scripts/check_browser.py
```

`scripts/check_browser.py`는 별도 `_test` DB만 비우고 임시 로그인 자격증명과 Web/Worker를 생성한 뒤 종료합니다. 개발용 `.env`와 기록은 변경하지 않습니다. `CHROMIUM_PATH`로 실행 파일 위치를 지정할 수 있습니다. 실제 키·실주문은 테스트하지 않습니다. 테스트 결과와 미검증 범위는 [docs/VALIDATION.md](docs/VALIDATION.md)를 확인하세요.

## 서버 환경변수

| 이름 | 필요 범위 / 의미 |
|---|---|
| DATABASE_URL | Web/Worker 공통 PostgreSQL URL. Render의 postgres://도 지원 |
| APP_ORIGIN | Web의 정확한 HTTPS 오리진, 마지막 경로/쿼리 없음 |
| OWNER_USERNAME / OWNER_PASSWORD_HASH | 단일 소유자 계정 / Argon2id 해시 |
| SESSION_SECRET | 최소32자 무작위 서버 키; 변경 시 기존 세션 무효 |
| COOKIE_SECURE | 운영 true, 로컬 loopback HTTP에서만 false |
| DATA_MODE | demo 기본. live-data는 별도 DB에서 읽기 연결 조사 전용 |
| ENABLE_LIVE_ORDERS | 기본false. true여도 미검증 실주문 어댑터는 차단 |
| FREE_TIER_MODE | true일 때 수동 갱신·API/분석/기록 보호 한도·워커/폴링 중단 |
| WORKER_INTERVAL_SECONDS | 기본5초, 최소2초. 공급자 요청 간격과 원본 지연은 별도 |
| KIS_APP_KEY / KIS_APP_SECRET | 읽기 연결 조사 시 Worker에만 안전하게 주입 |
| KIS_ACCOUNT_NUMBER / KIS_ACCOUNT_PRODUCT | 향후 실증권사 연동용 이름; 현재 계좌/주문에 사용하지 않음 |
| SEC_USER_AGENT | 연락처를 포함한 SEC 조사용 UA; 기본 수집 흐름 미연결 |
| ALPHAVANTAGE_API_KEY | 향후 뉴스 연결용 이름만 제공; 현재 미사용 |

키는 프런트 빌드 환경변수나 localStorage에 넣지 않습니다. LLM 없이 핵심 분석이 동작합니다. 실제 모드에서 API 오류를 합성값으로 바꾸지 않습니다. `live-data`가 정상 응답해도 호가·거래정지·시각/권한이 미확인이므로 후보/주문에 사용할 수 없습니다. 기존 데모 주문과 실제 시세를 섞지 않도록 **DATA_MODE별 별도 데이터베이스**를 사용하세요.

## 구조와 추가 문서

`backend/invest/providers`(공급자), `analysis`(지표·선정·위험·뉴스·보유 분석·백테스트), `orders.py`(주문·체결), `service.py`(스냅샷·포트폴리오), `worker.py`(수집·작업), `api.py/auth.py`(HTTP·보안), `migrations`(DB), `frontend/src`(UI), `scripts`(설치·실행)로 나뉩니다.

- [기능별 데이터 출처·기간·권한·연결 상태](docs/DATA_SOURCES.md)
- [설계·영속화·복구의 불변 조건](docs/ARCHITECTURE.md)
- [지표·기간 규칙·비용·백테스트 가정](docs/METHODOLOGY.md)
- [Render 배포 절차와 비용 확인](DEPLOY_RENDER.md)
- [배포 전 미연결 확인 목록](docs/DEPLOYMENT_CHECKLIST.md)

읽기 연결만 점검하려면 서버 비밀 환경변수를 설정한 뒤 `python scripts/probe_providers.py kis` 또는 `python scripts/probe_providers.py sec`를 실행하세요. 키가 없으면 연결 미설정으로 종료하며 합성 데이터를 반환하지 않습니다.

`target_pct`는 가정 비용을 반영한 USD 가격 손익 목표입니다. KRW 평가손익은 환율을 별도 반영하며 KRW 수익률을 보장하는 목표가 아닙니다. 강제 재시작 인수 검증은 별도 `invest_restart_test` DB를 만든 뒤 `python scripts/check_restart.py`로 실행할 수 있습니다.

## 무료 배포

[DEPLOY_FREE.md](DEPLOY_FREE.md)의 Render Free Web + Neon Free 구성으로 요청 시 실행과 사용량 보호를 구현했습니다. 기본 `render.yaml`은 무료 웹1개만 정의합니다. 공급자 계정의 카드 미등록·Free 플랜이 비용 차단의 전제이며 앱 카운터만으로 청구를 보장하지 않습니다. 무료 모드는 `.venv/bin/python scripts/check_browser.py --free`로 별도 검증합니다. 실제 원격 계정 연결·HTTPS 배포는 아직 수행하지 않았습니다.
