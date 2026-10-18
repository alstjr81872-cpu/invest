# 무료 배포: Web 1개 + Neon PostgreSQL

2026-10-18 확인. 기본 `render.yaml`은 **Render Free Web 1개만** 생성하는 Docker 설정이다. Worker·Render DB·디스크·cron·유료 인스턴스는 없다. React와 기존 Python API를 한 서비스에서 제공하고, Neon Free DB를 외부에 연결한다. **코드와 로컬 검증을 준비했으며 원격 계정 연결·배포는 아직 하지 않았다.**

Cloudflare Static Assets + Neon Functions도 무료 후보지만, Functions는 Node.js24만 지원해 Python 금융 로직 전체 이식이 필요하다. 이번에는 기존 계산·주문 처리를 유지하는 무료 웹 방식으로 구현했다. Docker는 무료 웹에서 그대로 사용할 수 있다.

## 비용이 생기지 않을 계정 조건

1. Render **Free 서비스 + 결제수단 없는 계정/워크스페이스**를 사용한다. 카드가 있으면 Free여도 대역폭·빌드 사용량 초과에 추가 요금이 생길 수 있다. 빌드 지출 한도도0으로 설정한다. 다른 서비스의 사용량도 공유된다.
2. Neon은 **Free 프로젝트**로 유지한다. 유료 플랜·자동 업그레이드를 켜지 않는다. compute 최대2CU 이하, 최소0.25CU, 비활동5분 autosuspend를 확인한다. 다른 앱/SQL 클라이언트의 지속 연결도 피한다.
3. 외부 ping/uptime 봇·예약 수집·상주 워커·프런트 자동 갱신은 사용하지 않는다. 합성 데이터만 사용하고 실제 유료 데이터 API는 연결하지 않는다.
4. Render Billing과 Neon Usage에서 실제 계정 한도를 확인한다. 앱 내부 카운터는 공급자의 계량기나 청구 차단 장치가 아니다. 공격 트래픽·다른 프로젝트·재시작·관리 쿼리·정적 파일 전송 등은 앱 예산과 별개다. 무료 한도 소진 시 이용 중단을 허용한다.

[Render 공식 무료 안내](https://render.com/docs/free.md)를 직접 읽어 확인했다: 월750 무료 인스턴스 시간(워크스페이스 공유),15분 유휴 후 절전,다음 요청으로 기동(약1분),카드가 없으면 전송량 초과 시 정지/빌드 초과 시 새 빌드 중지. 외부 DB 트래픽이 과도하면 서비스가 정지될 수 있다. 무료 Render DB는30일 만료하므로 사용하지 않는다. Render는 Free를 취미/실험용으로 안내한다.

[Neon 공식 플랜](https://github.com/neondatabase/website/blob/main/content/docs/introduction/plans.md): 확인 시점 Free 프로젝트당 월100CU-hours·1GB 저장·5GB 공개 전송. 계정 합계 저장 등 별도 제한도 있으므로 계정 화면을 우선한다. 2CU로 상시 실행하면 무료 범위를 넘기므로 절전을 유지한다.

## 앱에서 구현한 사용량 보호

`FREE_TIER_MODE=true`일 때 적용된다. 기본 무료 배포 파일에서 켜진다.

| 작업 | 하루 / 월 상한(UTC) |
|---|---:|
| API 전체 요청 | 80 / 300 |
| 수동 시세·체결 갱신 | 10 / 60 |
| 후보 분석 | 5 / 30 |
| 보유 분석 | 10 / 60 |
| 과거 실험 | 2 / 10 |
| 새 모의 주문 | 10 / 60 |

- 전체 API 예산에는 로그인 시도·세션 조회·차트·실패 요청도 포함한다. 대시보드를 한 요청으로 묶어 초기7회 조회를 줄였다. 작업 예산과 전체 예산을 모두 만족해야 한다. 한도 이후429와 재시도 시각을 반환한다. 읽기는 해당 작업 한도 소진 후에도 가능하지만 전체 API 한도에서는 중단된다.
- PostgreSQL 행 잠금으로 동시 요청/재시작을 거쳐 카운터를 유지한다. 프로세스당 분당30회도 제한한다. 차단 결과를 메모리에 보관해 반복 차단 요청이 DB를 계속 깨우지 않도록 한다. 재시작 후 첫 차단 확인은 DB를 조회한다.
- API 월300회가 각각2CU DB를6분 깨운다고 가정하면60CUh다. **보수적 계획 추정치이며 공급자 실제 사용량 보장은 아니다.** 마이그레이션/재시작/관리 접속/긴 작업/타 앱 사용량은 별도다. 실제 사용량이 커지면 계정에서 서비스를 중지한다.
- DB300MB, 추천200건, 작업500건, 주문1,000건, 이벤트10,000건에서 새 쓰기를 중단(507)한다. 모든 추천의 원본 스냅샷을 보존하되 개수에 상한을 둔다. 경계에서 진행 중 트랜잭션으로 약간 초과할 수 있으므로1GB보다 충분히 낮게 잡았다. 거래/분석 기록을 자동 삭제하지 않는다. 만료·폐기된 로그인 세션만 정리한다.
- WebSocket·5초 작업 폴링·무한 수집 루프를 비활성화한다. DB 연결은 NullPool로 요청 후 닫으며, 공개 health check는 DB를 조회하지 않는다. 정적 번들은 gzip·장기 캐시를 사용한다.
- 무료 모드에서는 실주문/live-data 실행을 거절한다. 모의 주문도 제출 시 체결하지 않는다. **시세·체결 갱신**을 누른 뒤 도착한 호가에서 최대3주씩 체결한다. 부분 체결의 나머지는 다음 갱신이 필요하다. 분석·과거 실험은 요청 중 처리한다. 작업이 중단되면 lease 만료 후 다음 요청에서 복구한다.
- 접속하지 않으면 수집·체결·위험 경보를 실행하지 않는다. 표시 가격은 마지막 수집값이고 오래된 가격의 새 매수는 계속 거절한다. 추천/보유 분석 시에도 시세를 한 번 갱신한다.

## 연결 순서

1. Neon에서 Free 프로젝트와 PostgreSQL DB를 만든다. Render Oregon에 가깝게 가능한 리전을 선택한다. **Direct connection URL(호스트에 `-pooler`가 없는 URL)**을 쓴다. 수집 리더의 세션 advisory lock 때문에 transaction pooler URL을 쓰면 안 된다.
2. Neon 연결 문자열을 Render의 비밀 환경변수 `DATABASE_URL`에 넣는다. `postgresql://`와 `postgres://`를 지원하며 TLS를 유지한다. 권장 쿼리: `sslmode=verify-full&sslrootcert=system&channel_binding=require`. libpq17 기반 고정 의존성에서 시스템 CA 검증을 지원한다. URL을 채팅/Git에 붙여 넣지 않는다.
3. `python scripts/hash_password.py`로 소유자 비밀번호의 Argon2id 해시를 만든다. Render의 `OWNER_PASSWORD_HASH`에 해시만 넣는다. `OWNER_USERNAME` 기본값은 owner이고 `SESSION_SECRET`은 Blueprint가 무작위 생성한다.
4. 코드를 GitHub에 반영한 뒤 Render New Blueprint로 이 저장소의 `render.yaml`을 선택한다. **서비스1개, plan=free, DB/Worker 없음**을 확인한다. 현재 클라우드 변경은 아직 커밋/push하지 않았다.
5. Docker 선택 시 **Docker Command는 비워 둔다.** Dockerfile CMD가 마이그레이션 후 웹 서버를 시작한다. `python -m invest.worker`는 어느 필드에도 넣지 않는다. 기존 네이티브 Python 서비스를 유지한다면 Build=`bash scripts/build_web.sh`, Start=`bash scripts/start_web.sh`; 무료 모드 환경변수도 동일하게 넣는다.
6. 운영 필수값: `FREE_TIER_MODE=true`, `DATA_MODE=demo`, `ENABLE_LIVE_ORDERS=false`, `COOKIE_SECURE=true`. 기본 Render 주소에서는 `RENDER_EXTERNAL_URL`을 정확한 로그인 Origin으로 자동 사용한다. 커스텀 도메인이면 `APP_ORIGIN`을 실제 HTTPS 오리진으로 지정한다. 새 비밀값 설정 뒤 재배포한다.
7. 안전한 터미널에 위 변수가 준비되어 있으면 `python scripts/check_free_config.py`로 값 노출 없이 설정을 검증한다. `--database`를 붙이면 DB에 한 번 접속해 TLS/마이그레이션/저장량도 확인한다. 앱을 처음 띄우기 전에는 마이그레이션이 없어 실패하는 것이 정상이다. 이 명령은 계정 청구 플랜/결제수단을 자동 검증하지 않는다.
8. 실제 Render HTTPS 주소에서 로그인→후보 분석→모의 주문→수동 갱신2회→분석→수동 매도→수동 갱신→기록을 확인한다. 개발 서버 테스트는 원격 배포 완료를 뜻하지 않는다. 원격 배포 자격증명과 DB URL이 현재 환경에 없어 이 단계는 아직 실행하지 못했다.

## 로컬 무료 모드 검증

기존 `.env`를 덮어쓰지 말고 환경변수로 선택한다. 개발용 PostgreSQL을 사용해 검증한다.

```bash
FREE_TIER_MODE=true .venv/bin/python scripts/run_local.py
# 별도 *_test DB에서 테스트. 개발/운영 DB에는 실행 금지.
.venv/bin/pytest -q
.venv/bin/python scripts/check_browser.py --free
```

원본 워커 방식은 `FREE_TIER_MODE=false`인 로컬 개발에서만 선택적으로 쓸 수 있다. 무료 배포에서는 워커 기동을 거절한다. 실제 시장 데이터·실주문은 여전히 미연결이다.
