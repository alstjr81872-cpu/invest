# Render 무료 배포

현재 기본 배포 구성은 **Free Web 1개 + 외부 Neon Free PostgreSQL**이다. 별도 유료 Worker와 Render DB를 생성하던 템플릿은 제거했다.

계정 비용 조건·환경변수·Neon Direct/TLS 연결·사용량 차단·검증 절차는 [DEPLOY_FREE.md](DEPLOY_FREE.md)를 따른다.

- Docker: Docker Command를 비워 둔다. 루트 `Dockerfile`의 CMD가 마이그레이션 후 웹 서버를 시작한다.
- 기존 Python 런타임: Build `bash scripts/build_web.sh`, Start `bash scripts/start_web.sh`.
- 필수 모드: `FREE_TIER_MODE=true`, `DATA_MODE=demo`, `ENABLE_LIVE_ORDERS=false`.
- **Background Worker를 만들거나 `python -m invest.worker`를 Start Command로 넣지 않는다.**
- 실제 원격 서비스/DB는 아직 생성·연결하지 않았다. 무료 요금제·카드 미등록·지출 한도는 공급자 계정에서 확인해야 한다.
