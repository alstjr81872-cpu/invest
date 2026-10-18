# 데이터 출처와 연결 계약

확인일: 2026-10-18 (한국 시각). **연결 준비와 실제 연결 성공은 다르다.** 실제 키·증권 계좌·Render 권한이 주어지지 않았으며, 실제 주문은 어떤 설정에서도 전송하지 않는다. 데모 실패를 실데이터로, 실데이터 실패를 합성 데이터로 바꾸지 않는다.

## 조사 근거

- 한국투자증권 [공식 포털](https://apiportal.koreainvestment.com/), [공식 샘플](https://github.com/koreainvestment/open-trading-api). HTTPS Git 조회·샘플 열람 성공. 검토한 커밋: `2077773a69a428daf63e148182511f068cc45de3`. `examples_llm/overseas_stock/{price,dailyprice,inquire_asking_price,order,order_rvsecncl,inquire_ccnl,inquire_balance}` 및 `examples_user/kis_auth.py`를 조사했다. API 포털 직접 열람은 네트워크 프록시 403으로 실패했다.
- [SEC 공식 API 문서](https://www.sec.gov/edgar/sec-api-documentation): 직접 접근 403. SEC 어댑터는 격리된 초안이며 모의 계약 테스트만 통과했다. 실제 SEC 데이터 수집, 이용 약관·연락처 User-Agent 검증은 미완료다. 미국 공시를 OpenDART로 대체하지 않는다.
- [Render 공식 FastAPI 예시](https://github.com/render-examples/fastapi/blob/main/render.yaml), [워커 예시](https://github.com/render-examples/celery/blob/main/render.yaml), [DB 참조 예시](https://github.com/render-examples/django/blob/main/render.yaml)는 열람했다. 현재 Blueprint·요금 페이지 직접 열람은 차단됐다. 현행 요금/모든 스키마 필드에 대한 검증으로 확대 해석하지 않는다.
- [FastAPI 공식 저장소](https://github.com/fastapi/fastapi), [거래소 달력 라이브러리 문서](https://github.com/gerrymanoim/exchange_calendars)는 열람했다. 패키지 버전은 PyPI/npm 메타데이터와 잠금파일로 고정한다. 직접 웹 문서를 확인하지 못한 API·한도는 확정해 표기하지 않는다.

## 기능별 가용성

| 기능 / 공급자 | 기간·주기 / 조정 | 구분·호출 정책 | 인증·비용·저장 권한 | 구현/검증 상태 |
|---|---|---|---|---|
| 합성 일봉·L1 호가·USD/KRW | 420거래일 일봉, 5초 폴링(설정 가능); 조정계수 1 | 완전한 합성 데이터; 원본 지연 0은 합성 시계에서만 의미 | 키/유료 API 없음; 로컬 생성, DB 보관 가능 | UI·계산·주문 흐름 검증, 실제 성과 근거 아님 |
| KIS 현재체결가 | 조회 당시 최근 체결값; 실제 체결 시각 계약 미검증 | `price`, `HHDFS00000300`; 수신 시각과 체결 시각 구분 | 앱키·시크릿 필요; 거래소 시세 권한/요금·저장 범위 미확인 | 읽기 어댑터·모의 계약 테스트; 실제 조회 미검증, 주문 사용 차단 |
| KIS 일봉 | `dailyprice`, 일봉 `GUBN=0`, `MODP=1` 요청 | `HHDFS76240000`; 기간/페이지 완전성 미검증 | 위와 동일; 계좌별 권한 확인 필요 | 원시 응답 staging 함수; 분석용 실데이터로 승격하지 않음 |
| KIS 1호가 | 공식 `inquire-asking-price`, `HHDFS76200100` 조사 | 통합/단일 거래소, 지연·세션 권한 미확인 | 실시간 사용 권한·재배포/저장 조건 확인 필요 | 조사만 완료, 미연결; 최근 체결가를 호가로 대체하지 않음 |
| KIS 매수/매도·취소·체결·잔고 | 공식 미국 매수 `TTTT1002U`, 매도 `TTTT1006U` 조사 | 샘플의 모의 매도 TR 설명과 치환 로직 차이도 있어 추측하지 않음 | 실제/공식 모의 앱키·계좌 분리; 계좌·주문유형·세션별 검증 필요 | **실주문·취소·계좌 대사 미연결**. KISBroker는 명시적으로 실패 |
| SEC EDGAR 제출 공시 | CIK 기준, 공시별 게시/접수 시각 필요 | 초안 `data.sec.gov/submissions/CIK{10자리}.json`; 연락처 UA 요구 | 연락처 `SEC_USER_AGENT`; 공식 Fair Access·저장/이용 조건 재확인 필요 | 초안 계약 테스트만. 실제 조회/과거 이용 가능 시각 검증 전 백테스트 제외 |
| 기업 IR / 실적 / 경제지표 일정 | 미확보 | 미확보 | 공인 공급자·시각·비용·저장 허용 확인 필요 | 미연결, 사건 위험 정상으로 간주하지 않음 |
| 미국 영문 뉴스 | 미확보. Alpha Vantage [공식 문서](https://www.alphavantage.co/documentation/#news-sentiment) 조사 시도 403 | 주소/TR/쿼터를 추측해 연결하지 않음 | API/저장/요약 권리 미확인 | 뉴스 매칭·중복 제거·제목 범위 구분만 구현; 실제 수집·한국어 본문 요약 미제공 |
| S&P 500 / 업종 / VIX / 금리 / 달러 / USDKRW | 실제 데이터 미확보 | 합성 지수 이름에 실제 지수 아님 표시 | 실제 공급자 및 권한 필요 | 합성 시장·업종만. 실제 지수·금리 등은 판단 불가 |
| 종목 마스터 / 거래정지 / 경보 / 기업행동 | 예시 보통주 6종과 CIK·거래소; 실제 PIT 마스터 미확보 | 불명 상태는 매수 차단 | 별도 권한·기업행동 이력 필요 | 데모에서는 가정값임을 명시. 실모드의 상태는 unknown |
| 과거 분봉 / 상장폐지 / 과거 지수 구성종목 | 미확보 | 1거래일 이내 전략 미지원 | 장기 PIT 데이터 비용/라이선스 필요 | 미지원, 가격 엔진 구현을 실전 전략 검증으로 표시하지 않음 |

## 검토한 KIS 계약의 정확한 범위

기준 URL은 공식 샘플의 `https://openapi.koreainvestment.com:9443`이며 토큰 발급은 `/oauth2/tokenP`의 `grant_type=client_credentials`, `appkey`, `appsecret`이다. 수신한 `expires_in` 동안 토큰을 재사용한다. 시세는 `/uapi/overseas-price/v1/quotations/price`의 `AUTH`, `EXCD`, `SYMB`, 응답 `output.last`를 검증한다. 시세 거래소 코드는 NAS/NYS이고, 주문 코드 NASD/NYSE와 혼용하지 않는다. 일봉은 `/uapi/overseas-price/v1/quotations/dailyprice`, `AUTH`, `EXCD`, `SYMB`, `GUBN`, `BYMD`, `MODP`, `output2`를 사용한다.

현행 공급자 쿼터를 확인하지 못했으므로 **초당 N건 지원을 주장하지 않는다**. 단일 워커는 보수적인 1.1초 요청 간격, 읽기 GET 최대 3회 재시도·짧은 캐시를 적용한다. 토큰 POST 및 향후 주문 POST에는 자동 재시도가 없다. 거절/타임아웃의 원문이나 키를 로그/오류 응답에 출력하지 않는다. 토큰은 워커 메모리에서만 재사용하며 재시작 시 새 토큰이 필요하다. 대규모 전체 시장 스캐닝은 미구현이며 고정 예시 6개로만 동작한다.

모든 봉/호가는 source, observed_at, collected_at, available_at을 갖는다. KIS의 `observed_at`은 어댑터 수신 시각이며 `timestamp_kind`와 `exchange_event_time=null`을 함께 기록한다. 이를 거래소 실시간 체결 시각으로 사용하지 않는다. 합성 이력의 과거 available_at은 **가상 실험 시계의 가정**이고 실제 당시 제공되었다는 뜻이 아니다. 생성 시각은 별도 metadata에 보존한다.

## 실제 연결 전 필요한 작업

1. 환경 설정에서 필요한 공식 도메인을 허용하고 문서·약관·권한·호가 시각을 확인한다. KIS의 9443 포트를 지원하는 egress 정책도 확인한다.
2. 앱키는 서버 워커에만 주입하고 KIS 시세 최소 조회를 실행한다. 현재 체결가 수신 성공과 실시간 시세 권한 검증을 구분한다.
3. SEC 연락처 UA, 뉴스/일정/기업행동 공급자의 권리와 비용을 확인하고 정상·없음·수집 실패를 구분하는 어댑터를 검증한다.
4. 실제 주문은 별도 구현·계좌 및 공식 샌드박스 테스트·Render 출구 IP/리전 허용·잔고/체결 대사 검증이 필요하다. 환경 플래그만 켜도 주문이 실행되도록 열어두지 않았다.
