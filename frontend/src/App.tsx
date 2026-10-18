import { useState, useEffect, Suspense } from "react";
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  ArrowDownRight,
  BriefcaseBusiness,
  Check,
  ChevronRight,
  FileClock,
  FlaskConical,
  LayoutDashboard,
  LogOut,
  RefreshCw,
  Settings2,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
  WifiOff,
  X,
} from "lucide-react";
import { api, setCsrf } from "./api";
import type {
  Json,
  Research,
  Candidate,
  Portfolio,
  Preferences,
  Order,
  Position,
  Job,
} from "./types";
import {
  Logo,
  Badge,
  DualTime,
  Empty,
  Modal,
  CandidateCard,
  Chart,
  Evidence,
  TradeForm,
  PositionCard,
  SellForm,
  AnalysisCard,
  Backtest,
  SettingsForm,
  money,
  signed,
  statusLabel,
} from "./components";
import Login from "./Login";
const navs = [
  { id: "research", label: "추천 종목", Icon: LayoutDashboard },
  { id: "portfolio", label: "내 투자", Icon: BriefcaseBusiness },
  { id: "records", label: "분석 기록", Icon: FileClock },
  { id: "settings", label: "설정", Icon: Settings2 },
];
export default function App() {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null),
    [page, setPage] = useState("research"),
    [status, setStatus] = useState<Json | null>(null),
    [pf, setPf] = useState<Portfolio | null>(null),
    [prefs, setPrefs] = useState<Preferences | null>(null),
    [research, setResearch] = useState<Research | null>(null),
    [orders, setOrders] = useState<Order[]>([]),
    [jobs, setJobs] = useState<Job[]>([]),
    [events, setEvents] = useState<Json[]>([]),
    [detail, setDetail] = useState<Candidate | null>(null),
    [sell, setSell] = useState<Position | null>(null),
    [stream, setStream] = useState("connecting"),
    [busy, setBusy] = useState(""),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [tab, setTab] = useState("analysis"),
    [loading, setLoading] = useState(false);
  useEffect(() => {
    api<{ csrf: string }>("/session")
      .then((s) => {
        setCsrf(s.csrf);
        setAuthenticated(true);
      })
      .catch(() => setAuthenticated(false));
    const expired = () => {
      setAuthenticated(false);
      setNotice("로그인이 만료됐어요. 다시 로그인하세요.");
    };
    window.addEventListener("session-expired", expired);
    return () => window.removeEventListener("session-expired", expired);
  }, []);
  async function refreshRecords() {
    if (status?.free_tier?.enabled) {
      applyDashboard(await api<Json>("/dashboard"));
      return;
    }
    const [a, b, c] = await Promise.all([
      api<Order[]>("/orders"),
      api<Job[]>("/jobs"),
      api<Json[]>("/history"),
    ]);
    setOrders(a);
    setJobs(b);
    setEvents(c);
  }
  function applyDashboard(data: Json) {
    setStatus(data.status);
    setPf(data.portfolio);
    setPrefs(data.settings);
    setResearch(data.research);
    setOrders(data.orders);
    setJobs(data.jobs);
    setEvents(data.events);
  }
  async function initialLoad() {
    setError("");
    setLoading(true);
    try {
      applyDashboard(await api<Json>("/dashboard"));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }
  async function manualRefresh() {
    await run("refresh", async () => {
      applyDashboard(await api<Json>("/refresh", "POST"));
      setNotice(
        "한 번 갱신했어요. 미체결 모의 주문은 다음 갱신에서 다시 확인해요.",
      );
    });
  }
  useEffect(() => {
    if (authenticated) void initialLoad();
  }, [authenticated]);
  useEffect(() => {
    if (!authenticated || !status || status.free_tier?.enabled) return;
    let socket: WebSocket | null = null,
      retry = 0,
      stopped = false,
      cursor = 0,
      lastFrame = Date.now(),
      timer: ReturnType<typeof setTimeout>;
    function connect() {
      if (stopped || !navigator.onLine) {
        setStream("disconnected");
        return;
      }
      setStream("connecting");
      lastFrame = Date.now();
      socket = new WebSocket(
        `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/api/stream?after=${cursor}`,
      );
      socket.onopen = () => {
        retry = 0;
        setStream("connected");
      };
      socket.onmessage = (e) => {
        lastFrame = Date.now();
        const data = JSON.parse(e.data);
        if (data.type === "snapshot") {
          setPf(data.portfolio);
          setStatus(data.status);
          cursor = data.cursor;
          if (data.events.length) void refreshRecords().catch(() => {});
        } else {
          setStream("error");
          setError(data.message);
        }
      };
      socket.onclose = (e) => {
        if (stopped) return;
        setStream("disconnected");
        if (e.code === 1008) {
          setAuthenticated(false);
          return;
        }
        if (navigator.onLine)
          timer = setTimeout(
            connect,
            Math.min(30000, 1000 * 2 ** retry++) + Math.random() * 300,
          );
      };
      socket.onerror = () => socket?.close();
    }
    const offline = () => {
      clearTimeout(timer);
      setStream("disconnected");
      socket?.close();
    };
    const online = () => {
      clearTimeout(timer);
      if (!socket || socket.readyState > 1) connect();
    };
    window.addEventListener("offline", offline);
    window.addEventListener("online", online);
    const watchdog = setInterval(() => {
      if (Date.now() - lastFrame > 10000) {
        setStream("disconnected");
        socket?.close();
      }
    }, 2000);
    connect();
    return () => {
      stopped = true;
      clearTimeout(timer);
      clearInterval(watchdog);
      window.removeEventListener("offline", offline);
      window.removeEventListener("online", online);
      socket?.close();
    };
  }, [authenticated, !!status, status?.free_tier?.enabled]);
  useEffect(() => {
    if (!authenticated || !status || status.free_tier?.enabled) return;
    const timer = setInterval(() => {
      void api<Job[]>("/jobs")
        .then(setJobs)
        .catch(() => {});
    }, 5000);
    return () => clearInterval(timer);
  }, [authenticated, !!status, status?.free_tier?.enabled]);
  async function run(label: string, action: () => Promise<unknown>) {
    if (busy) return;
    setBusy(label);
    setError("");
    try {
      await action();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  async function newResearch() {
    await run("research", async () => {
      setResearch(await api<Research>("/research", "POST"));
      setNotice("완성 일봉과 최신 합성 호가로 후보를 계산했어요.");
    });
  }
  async function analyze(id?: string) {
    await run("analysis", async () => {
      await api("/analysis", "POST", { instrument_id: id ?? null });
      await refreshRecords();
      setPage("records");
      setTab("analysis");
      setNotice(
        status?.free_tier?.enabled
          ? "요청 시점의 스냅샷으로 분석했어요."
          : "분석을 요청했어요. 워커가 최신 스냅샷으로 계산합니다.",
      );
    });
  }
  async function afterOrder() {
    await refreshRecords();
    if (!status?.free_tier?.enabled) setPf(await api("/portfolio"));
    setPage("portfolio");
    setDetail(null);
    setSell(null);
    setNotice("주문이 접수됐어요. 체결 수량과 상태를 확인하세요.");
  }
  if (authenticated === null)
    return (
      <main className="boot" role="status">
        <Logo />
        <p>연구실을 준비하고 있어요…</p>
      </main>
    );
  if (!authenticated)
    return (
      <Login
        onLogin={() => {
          setAuthenticated(true);
          setNotice("");
        }}
      />
    );
  const mode =
      status?.mode === "live-data"
        ? "실제 시세 조회 · 주문 불가"
        : "데모 · 모의 투자",
    freeMode = !!status?.free_tier?.enabled,
    feed = (freeMode || stream === "connected") && status?.worker.connected,
    shortlist =
      research?.candidates.filter((c) => research.shortlist.includes(c.id)) ??
      [];
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Logo />
        <span className="sidebar-label">MY WORKSPACE</span>
        <nav aria-label="주 메뉴">
          {navs.map(({ id, label, Icon }) => (
            <button
              key={id}
              onClick={() => setPage(id)}
              className={page === id ? "active" : ""}
              aria-current={page === id ? "page" : undefined}
            >
              <Icon size={22} />
              {label}
              {page === id && <span className="nav-active-dot" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="private-note">
            <ShieldCheck size={23} />
            <div>
              나만의 투자 공간<small>모의 투자 기본 · 실제 주문 잠금</small>
            </div>
          </div>
          <button
            className="logout"
            onClick={() =>
              void run("logout", async () => {
                await api("/logout", "POST");
                setAuthenticated(false);
              })
            }
          >
            <LogOut size={19} />
            로그아웃
          </button>
          <span className="version">SHORTLIST / RESEARCH V0.1</span>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="mobile-brand">
            shortlist<span>.</span>
          </div>
          <div className="breadcrumb">
            나의 연구실 <ChevronRight size={16} />
            {navs.find((n) => n.id === page)?.label}
          </div>
          <div className="topbar-right">
            <Badge tone="blue">
              <FlaskConical size={16} />
              {mode}
            </Badge>
            <span className="owner-avatar" aria-label="소유자 계정">
              나
            </span>
          </div>
        </header>
        <main id="main-content">
          <div className="page-heading">
            <div>
              <p className="eyebrow">
                {page === "research"
                  ? "MAKE YOUR NEXT MOVE"
                  : page === "portfolio"
                    ? "MY PAPER PORTFOLIO"
                    : page === "records"
                      ? "EVIDENCE & HISTORY"
                      : "MY INVESTMENT RULES"}
              </p>
              <h1>
                {page === "research"
                  ? "다음 투자를, 근거 있게."
                  : page === "portfolio"
                    ? "내 투자의 흐름을 한눈에"
                    : page === "records"
                      ? "판단의 과정을 기록해요"
                      : "나에게 맞는 투자 기준"}
              </h1>
              <p className="muted">
                {page === "research"
                  ? "가능성을 살피고, 감당할 위험부터 정해요."
                  : page === "portfolio"
                    ? "체결된 수량만 추적해요. 분석과 매도는 별개의 행동이에요."
                    : page === "records"
                      ? "계산 결과와 과거 실험, 체결 기록을 구분해요."
                      : "설정 예시는 검증된 투자 전략의 기본값이 아니에요."}
              </p>
            </div>
            <div className="market-state">
              <span className={`status-dot ${feed ? "green" : ""}`} />
              {status?.market.label ?? "상태 확인 중"}
              <small>
                {freeMode
                  ? "무료 모드 · 버튼을 누를 때만 갱신"
                  : feed
                    ? `합성 시세 수신 · ${status?.poll_seconds}초 간격`
                    : "데이터 연결 확인 중"}
              </small>
            </div>
          </div>
          <div className="demo-banner">
            <FlaskConical size={20} />
            <span>
              <strong>{mode}</strong>
              {status?.mode === "demo"
                ? " · 모든 가격·호가·환율은 합성 데이터예요. 실제 시장 분석이나 투자 성과가 아닙니다."
                : " · 필수 데이터가 미확인되면 새 매수를 차단합니다."}
            </span>
          </div>
          {freeMode && (
            <section className="alert info" aria-label="무료 사용량 보호">
              <div>
                <strong>무료 모드 · 수동 갱신</strong>
                <p>
                  창을 닫으면 수집·모의 체결·경보가 실행되지 않아요. 주문 후
                  시세 갱신으로 체결 상태를 확인하세요.
                </p>
                <p>
                  이번 달 API {status?.free_tier.usage.monthly.api.used} /{" "}
                  {status?.free_tier.usage.monthly.api.limit}회 · 보호 한도에서
                  중단
                </p>
                <p>
                  최근 수집: <DualTime value={status?.worker.heartbeat} />
                </p>
                <button
                  className="button secondary"
                  disabled={!!busy || loading}
                  onClick={() => void manualRefresh()}
                >
                  <RefreshCw size={18} /> 시세·체결 갱신
                </button>
              </div>
            </section>
          )}
          {!feed && !freeMode && (
            <div className="alert danger" role="alert">
              <WifiOff size={20} />
              <div>
                시세 또는 워커 연결을 확인하고 있어요. 오래된 데이터에서는 새
                주문과 최신 대응 판단이 제한돼요.
                <button
                  className="text-button"
                  onClick={() => void initialLoad()}
                >
                  상태 다시 확인
                </button>
              </div>
            </div>
          )}
          {error && (
            <div className="alert danger" role="alert">
              <TriangleAlert size={20} />
              <span>{error}</span>
              <button
                className="icon-button"
                aria-label="오류 닫기"
                onClick={() => setError("")}
              >
                <X size={18} />
              </button>
            </div>
          )}
          {notice && (
            <div className="alert info" role="status">
              <Check size={20} />
              <span>{notice}</span>
              <button
                className="icon-button"
                aria-label="알림 닫기"
                onClick={() => setNotice("")}
              >
                <X size={18} />
              </button>
            </div>
          )}
          {events
            .filter((event) => event.kind === "alert")
            .slice(0, 3)
            .map((event) => (
              <div className="alert warning" role="alert" key={event.id}>
                <TriangleAlert size={20} />
                <div>
                  {event.payload.message ?? "위험 상태를 확인하세요."}
                  <br />
                  <DualTime value={event.at} />
                </div>
              </div>
            ))}
          {loading && <p role="status">데이터를 불러오고 있어요…</p>}
          {pf && (
            <section className="summary-grid" aria-label="모의 계좌 요약">
              <div className="summary-main card">
                <span className="label">
                  모의 총 평가금액 <Badge>USD</Badge>
                </span>
                <strong className="big-number">{money(pf.equity)}</strong>
                <div
                  className={pf.unrealized_pnl >= 0 ? "positive" : "negative"}
                >
                  {pf.unrealized_pnl >= 0 ? (
                    <ArrowUpRight size={20} />
                  ) : (
                    <ArrowDownRight size={20} />
                  )}{" "}
                  미실현 {money(pf.unrealized_pnl)}
                  <span className="muted"> · 체결가 기준</span>
                </div>
                {!pf.valuation_complete && (
                  <p className="warning-text">
                    오래되거나 누락된 평가 시세 포함
                  </p>
                )}
              </div>
              <div className="summary-sub card">
                <span className="label">매수 가능 현금</span>
                <strong>{money(pf.available_cash)}</strong>
                <span className="muted">주문 예약 {money(pf.reserved)}</span>
              </div>
              <div className="summary-sub card">
                <span className="label">보유 종목</span>
                <strong>
                  {pf.positions.length}
                  <small> 종목</small>
                </strong>
                <span className="muted">
                  최대 {prefs?.max_positions ?? "—"}종목 · 현금 매수
                </span>
              </div>
            </section>
          )}
          {page === "research" && (
            <>
              <section className="research-hero">
                <div className="hero-content">
                  <Badge tone="blue">
                    <Sparkles size={16} /> 숫자로 살펴보는 투자 기회
                  </Badge>
                  <h2>
                    좋은 기회는,
                    <br />내 기준에 맞는 기회.
                  </h2>
                  <p>
                    목표와 기간, 손실 예산을 함께 확인해요.
                    <br />
                    조건에 맞는 종목이 없으면 매수를 보류합니다.
                  </p>
                  <button
                    className="primary"
                    onClick={() => void newResearch()}
                    disabled={!!busy || (!freeMode && !feed)}
                  >
                    <RefreshCw
                      size={20}
                      className={busy === "research" ? "spin" : ""}
                    />
                    {busy === "research"
                      ? "후보를 계산하고 있어요…"
                      : "후보 분석하기"}
                  </button>
                </div>
                <div className="hero-rule">
                  <span className="eyebrow">MY INVESTMENT PLAN</span>
                  <div>
                    <span>보유 기간</span>
                    <strong>
                      {prefs?.holding_days ?? "—"}
                      <small> 거래일</small>
                    </strong>
                  </div>
                  <div>
                    <span>목표 순수익률</span>
                    <strong>
                      {prefs?.target_pct ?? "—"}
                      <small>%</small>
                    </strong>
                  </div>
                  <div>
                    <span>거래당 손실 예산</span>
                    <strong>{money(prefs?.loss_budget_usd)}</strong>
                  </div>
                  <button
                    className="text-button"
                    onClick={() => setPage("settings")}
                  >
                    투자 기준 바꾸기
                    <ArrowRight size={17} />
                  </button>
                </div>
              </section>
              <section className="market-grid">
                <div className="card">
                  <span className="label">
                    <Activity size={18} /> 시장의 흐름
                  </span>
                  <h3>
                    {research?.market.state ?? "분석 전"}
                    <span className="soft-text"> · 합성 지수</span>
                  </h3>
                  <p>
                    {research?.market.facts?.[0] ??
                      "분석 버튼을 눌러 완성 일봉을 확인하세요."}
                  </p>
                  <small className="muted">
                    {research?.market.name ?? "실제 S&P 500 시세 미연결"}
                  </small>
                </div>
                <div className="card">
                  <span className="label">
                    <ShieldCheck size={18} /> 데이터와 근거
                  </span>
                  <h3>
                    규칙 기반 <span className="soft-text">· 미검증 가설</span>
                  </h3>
                  <p>점수는 적합도예요. 상승확률이 아닙니다.</p>
                  <small className="muted">목표 달성 확률: 산출하지 않음</small>
                </div>
              </section>
              <section>
                <div className="section-heading">
                  <div>
                    <span className="eyebrow">YOUR SHORTLIST</span>
                    <h2>
                      조건을 통과한 후보{" "}
                      <span className="count">{shortlist.length}</span>
                    </h2>
                  </div>
                  {research && <DualTime value={research.created_at} />}
                </div>
                {!research ? (
                  <Empty title="투자 기준으로 첫 분석을 시작해 보세요">
                    데모 데이터로 후보 선정부터 모의 매도까지 체험할 수 있어요.
                  </Empty>
                ) : !shortlist.length ? (
                  <Empty title="지금은 매수 보류가 적합해요">
                    목표·위험·데이터 조건을 통과한 후보가 없어요. 아래 탈락
                    사유를 확인하세요.
                  </Empty>
                ) : (
                  <div className="candidate-grid">
                    {shortlist.map((c, index) => (
                      <CandidateCard
                        key={c.id}
                        candidate={c}
                        index={index}
                        onDetail={() => setDetail(c)}
                      />
                    ))}
                  </div>
                )}
              </section>
              {research && (
                <section className="card comparison">
                  <div className="section-heading">
                    <div>
                      <h2>전체 후보 비교</h2>
                      <p className="muted">
                        통과와 탈락 사유를 함께 확인하세요.
                      </p>
                    </div>
                    <Badge>{research.candidates.length}개 분석</Badge>
                  </div>
                  <div
                    className="table-scroll"
                    tabIndex={0}
                    aria-label="후보 비교 표 가로 스크롤"
                  >
                    <table>
                      <thead>
                        <tr>
                          <th>종목 / 상태</th>
                          <th>기준 가격</th>
                          <th>진입 / 목표 / 손절</th>
                          <th>기간 / 전략</th>
                          <th>비용 차감 손익비</th>
                          <th>적합도 / 근거 수준</th>
                          <th>주요 위험</th>
                        </tr>
                      </thead>
                      <tbody>
                        {research.candidates.map((c) => (
                          <tr key={c.id}>
                            <td>
                              <button
                                className="table-ticker"
                                onClick={() => setDetail(c)}
                              >
                                {c.ticker}
                                <ChevronRight size={16} />
                              </button>
                              <span>{c.status}</span>
                            </td>
                            <td>
                              {money(c.price)}
                              <small>
                                <DualTime value={c.as_of} />
                              </small>
                            </td>
                            <td>
                              {money(c.entry)}
                              <small>
                                목표 {money(c.target)}
                                <br />
                                손절 {money(c.stop)}
                              </small>
                            </td>
                            <td>
                              {c.holding_days}거래일
                              <small>{c.strategy ?? "확인 불가"}</small>
                            </td>
                            <td>{c.risk.risk_reward?.toFixed(2) ?? "—"} : 1</td>
                            <td>
                              {c.score ?? "—"}점<small>{c.evidence}</small>
                            </td>
                            <td className="risk-cell">
                              {c.risks[0] ?? "확인 불가"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <p className="muted footnote">
                    분석 유효기간 15분 · 가격 추격 제한 0.5% · 뉴스는 점수에
                    가산하지 않아요.
                  </p>
                </section>
              )}
            </>
          )}
          {page === "portfolio" && pf && (
            <>
              <div className="section-heading">
                <div>
                  <h2>
                    내 보유 종목{" "}
                    <span className="count">{pf.positions.length}</span>
                  </h2>
                  <p className="muted">
                    조회 간격 {status?.poll_seconds ?? "—"}초 · 합성 시세, 실제
                    실시간 시세 아님
                  </p>
                </div>
                <button
                  className="primary"
                  disabled={!!busy || !pf.positions.length || (!freeMode && !feed)}
                  onClick={() => void analyze()}
                >
                  <Sparkles size={20} />
                  전체 분석
                </button>
              </div>
              {!pf.positions.length ? (
                <Empty title="아직 체결된 보유 종목이 없어요">
                  추천 종목에서 모의 주문을 제출하고 체결 상태를 확인하세요.
                </Empty>
              ) : (
                <div className="positions">
                  {pf.positions.map((p) => (
                    <PositionCard
                      key={p.id}
                      position={p}
                      busy={!!busy}
                      onAnalyze={() => void analyze(p.id)}
                      onSell={() => setSell(p)}
                    />
                  ))}
                </div>
              )}
              <section className="card">
                <div className="section-heading">
                  <div>
                    <h2>주문 / 체결 상태</h2>
                    <p className="muted">
                      접수는 매수 완료가 아니에요. 첫 부분 체결부터 보유로
                      추적합니다.
                    </p>
                  </div>
                  <Badge>모의 계좌</Badge>
                </div>
                {!orders.length ? (
                  <p className="muted">제출한 주문이 없어요.</p>
                ) : (
                  <div className="order-list">
                    {orders.map((o) => (
                      <div className="order-row" key={o.id}>
                        <div>
                          <strong>
                            {research?.candidates.find(
                              (c) => c.id === o.instrument_id,
                            )?.ticker ??
                              pf.positions.find((p) => p.id === o.instrument_id)
                                ?.ticker ??
                              o.instrument_id}
                          </strong>
                          <span
                            className={
                              o.side === "buy" ? "positive" : "negative"
                            }
                          >
                            {" "}
                            모의 {o.side === "buy" ? "매수" : "매도"}
                          </span>
                          <small>
                            {statusLabel[o.status] ?? o.status} · {o.filled}/
                            {o.quantity}주 체결
                          </small>
                        </div>
                        <div className="order-prices">
                          <strong>지정가 {money(o.limit_price)}</strong>
                          <small>
                            표시 {money(o.displayed_price)} · 체결 평균{" "}
                            {o.filled ? money(o.average_price) : "미체결"}
                          </small>
                          <small>비용 {money(o.fees)}</small>
                        </div>
                        {["accepted", "pending", "partially_filled"].includes(
                          o.status,
                        ) && (
                          <button
                            className="secondary"
                            disabled={!!busy}
                            onClick={() =>
                              void run("cancel", async () => {
                                await api(`/orders/${o.id}/cancel`, "POST");
                                await refreshRecords();
                              })
                            }
                          >
                            잔량 취소
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </section>
            </>
          )}
          {page === "records" && (
            <>
              <div className="tab-group" role="tablist" aria-label="기록 유형">
                {[
                  ["analysis", "보유 분석"],
                  ["backtest", "과거 검증"],
                  ["history", "거래 기록"],
                ].map(([id, label]) => (
                  <button
                    key={id}
                    role="tab"
                    aria-selected={tab === id}
                    className={tab === id ? "selected" : ""}
                    onClick={() => setTab(id)}
                  >
                    {label}
                  </button>
                ))}
              </div>
              {tab === "analysis" && (
                <>
                  {!jobs.filter((j) => j.kind === "analysis").length ? (
                    <Empty title="분석 기록이 아직 없어요">
                      보유 종목의 분석하기 버튼으로 가격·추세·위험의 변화를
                      확인하세요.
                    </Empty>
                  ) : (
                    jobs
                      .filter((j) => j.kind === "analysis")
                      .map((j) => <AnalysisCard job={j} key={j.id} />)
                  )}
                </>
              )}
              {tab === "backtest" && (
                <Backtest
                  jobs={jobs.filter((j) => j.kind === "backtest")}
                  research={research}
                  busy={!!busy}
                  onRun={(id, days) =>
                    void run("backtest", async () => {
                      await api("/backtest", "POST", {
                        instrument_id: id,
                        holding_days: days,
                      });
                      await refreshRecords();
                    })
                  }
                />
              )}
              {tab === "history" && (
                <section className="card">
                  <h2>영속 거래 기록</h2>
                  <p className="muted">
                    추천 당시 설정과 근거, 주문·체결은 PostgreSQL에 저장돼요.
                  </p>
                  {events.length ? (
                    events.map((e) => (
                      <div className="history-row" key={e.id}>
                        <span className="history-dot" />
                        <div>
                          <strong>
                            {{
                              research: "후보 분석 저장",
                              order: "주문 상태 변경",
                              fill: "모의 체결",
                              analysis: "보유 분석",
                              backtest: "과거 실험",
                              alert: "위험 알림",
                            }[e.kind as string] ?? e.kind}
                          </strong>
                          <p>
                            {e.payload.message ??
                              (e.payload.quantity
                                ? `${e.payload.quantity}주 · ${money(e.payload.price)} · ${statusLabel[e.payload.status] ?? ""}`
                                : e.payload.status
                                  ? statusLabel[e.payload.status]
                                  : e.payload.shortlist_count !== undefined
                                    ? `통과 후보 ${e.payload.shortlist_count}개`
                                    : e.payload.state
                                      ? statusLabel[e.payload.state]
                                      : "기록 저장")}
                          </p>
                          <DualTime value={e.at} />
                        </div>
                      </div>
                    ))
                  ) : (
                    <p>아직 기록이 없어요.</p>
                  )}
                </section>
              )}
            </>
          )}
          {page === "settings" && prefs && (
            <>
              <SettingsForm
                initial={prefs}
                candidates={research?.candidates ?? []}
                busy={!!busy}
                onSave={(value) =>
                  void run("settings", async () => {
                    setPrefs(await api<Preferences>("/settings", "PUT", value));
                    setNotice(
                      "투자 기준을 저장했어요. 후보를 다시 분석하세요.",
                    );
                  })
                }
              />
              <section className="card">
                <div className="section-heading">
                  <h2>데이터 연결 상태</h2>
                  <Badge tone={feed ? "green" : "amber"}>
                    {freeMode
                      ? "요청 시에만 실행"
                      : feed
                        ? "워커 실행 중"
                        : "워커 확인 필요"}
                  </Badge>
                </div>
                <div className="connection-list">
                  {status?.providers.map((p: Json) => (
                    <div key={p.name}>
                      <span>{p.name}</span>
                      <strong>{p.state}</strong>
                    </div>
                  ))}
                </div>
                <div className="alert warning">
                  <TriangleAlert size={20} />
                  <div>
                    실제 주문: 비활성화
                    <p>
                      계좌·권한·거래정지·호가·주문 조회·대사 검증이 필요합니다.
                    </p>
                  </div>
                </div>
                <p className="muted">
                  API 키는 서버 환경변수에서만 설정하세요. 브라우저에 입력하거나
                  저장하지 않습니다.
                </p>
                <details>
                  <summary>
                    {freeMode ? "수동 갱신과 제한 사항" : "워커와 제한 사항"}
                  </summary>
                  <p>
                    최종 heartbeat:{" "}
                    <DualTime value={status?.worker.heartbeat} />
                  </p>
                  <p>
                    원본 지연과 화면 갱신 주기는 별개예요. 합성 시세는 실제
                    시장과 무관합니다.
                  </p>
                  {status?.limitations.map((s: string) => <p key={s}>{s}</p>)}
                  {status?.worker.detail.errors?.map((e: Json) => (
                    <p key={e.ticker}>
                      {e.ticker}: {e.code}
                    </p>
                  ))}
                </details>
              </section>
            </>
          )}
          <footer className="page-footer">
            <ShieldCheck size={17} />
            <p>
              수익을 보장하지 않는 투자 연구 도구 · 손실 예산은 실제 손실 상한이
              아닙니다.
              <br />
              모의 체결은 실제 체결과 다르며, 경고는 증권사에 접수된 보호 주문이
              아닙니다.
            </p>
          </footer>
        </main>
      </div>
      <nav className="mobile-nav" aria-label="모바일 주 메뉴">
        {navs.map(({ id, label, Icon }) => (
          <button
            key={id}
            aria-current={page === id ? "page" : undefined}
            className={page === id ? "active" : ""}
            onClick={() => setPage(id)}
          >
            <Icon size={23} />
            {label}
          </button>
        ))}
      </nav>
      {detail && research && (
        <Modal
          title={`${detail.name} · ${detail.ticker}`}
          wide
          onClose={() => setDetail(null)}
        >
          <div className="detail-price">
            <strong>{money(detail.price)}</strong>
            <Badge>{detail.status}</Badge>
            <Badge tone="amber">데모 데이터</Badge>
          </div>
          <DualTime value={detail.as_of} />
          <Suspense fallback={<p>차트를 불러오고 있어요…</p>}>
            <Chart
              id={detail.id}
              levels={{
                entry: detail.entry,
                target: detail.target,
                stop: detail.stop,
              }}
            />
          </Suspense>
          <div className="detail-grid">
            <div>
              <Evidence candidate={detail} />
            </div>
            <TradeForm
              candidate={detail}
              research={research}
              cash={pf?.available_cash ?? 0}
              onSuccess={afterOrder}
            />
          </div>
        </Modal>
      )}
      {sell && (
        <Modal title={`${sell.ticker} 모의 매도`} onClose={() => setSell(null)}>
          <SellForm position={sell} onSuccess={afterOrder} />
        </Modal>
      )}
    </div>
  );
}
