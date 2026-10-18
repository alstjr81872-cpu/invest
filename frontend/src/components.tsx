import {
  useEffect,
  useRef,
  useState,
  lazy,
  Suspense,
  type ReactNode,
  type FormEvent,
} from "react";
import {
  ArrowRight,
  ArrowUpRight,
  ArrowDownRight,
  BarChart3,
  Check,
  ChevronRight,
  CircleHelp,
  Search,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
  X,
} from "lucide-react";
import { api, HttpError } from "./api";
import type {
  Candidate,
  Position,
  Research,
  Preferences,
  Job,
  Json,
} from "./types";
export const Chart = lazy(() => import("./Chart"));
export const money = (v: number | null | undefined, currency = "USD") =>
  v == null
    ? "확인 불가"
    : new Intl.NumberFormat("ko-KR", {
        style: "currency",
        currency,
        currencyDisplay: "narrowSymbol",
        maximumFractionDigits: currency === "KRW" ? 0 : 2,
      }).format(v);
export const signed = (v: number, suffix = "") =>
  `${v >= 0 ? "+" : "−"}${Math.abs(v).toLocaleString("ko-KR", { maximumFractionDigits: 2 })}${suffix}`;
const time = (value: string | undefined, zone: string) =>
  value
    ? new Intl.DateTimeFormat("ko-KR", {
        timeZone: zone,
        month: "numeric",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      }).format(new Date(value))
    : "확인 불가";
export const statusLabel: Record<string, string> = {
  accepted: "주문 접수",
  pending: "미체결",
  partially_filled: "부분 체결",
  filled: "전량 체결",
  cancelled: "취소",
  rejected: "거절",
  needs_review: "상태 확인 필요",
  queued: "대기",
  running: "분석 중",
  completed: "완료",
  failed: "실패",
};
const sectors: Record<string, string> = {
  technology: "기술",
  consumer: "소비",
  financials: "금융",
  healthcare: "헬스케어",
};
export function Logo() {
  return (
    <div className="brand">
      <span className="brand-mark">
        <BarChart3 size={26} />
      </span>
      <span>
        shortlist<span className="brand-dot">.</span>
        <small>나의 투자 연구실</small>
      </span>
    </div>
  );
}
export function DualTime({ value }: { value: string | undefined }) {
  return (
    <span className="dual-time">
      뉴욕 {time(value, "America/New_York")}
      <br />
      서울 {time(value, "Asia/Seoul")}
    </span>
  );
}
export function Badge({
  children,
  tone = "",
}: {
  children: ReactNode;
  tone?: string;
}) {
  return <span className={`badge ${tone}`}>{children}</span>;
}
export function Empty({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="empty">
      <Search size={32} />
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}
export function Modal({
  title,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null),
    closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const before = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const node = ref.current;
    node?.focus();
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeRef.current();
      if (event.key === "Tab" && node) {
        const items = [
            ...node.querySelectorAll<HTMLElement>(
              'button:not([disabled]),input:not([disabled]),select:not([disabled]),summary,a[href],[tabindex="0"]',
            ),
          ],
          first = items[0],
          last = items[items.length - 1];
        if (
          event.shiftKey &&
          (document.activeElement === first || document.activeElement === node)
        ) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener("keydown", handler);
    return () => {
      document.body.style.overflow = before;
      document.removeEventListener("keydown", handler);
      previous?.focus();
    };
  }, []);
  return (
    <div className="modal-backdrop">
      <div
        className={`modal ${wide ? "wide" : ""}`}
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
      >
        <div className="modal-heading">
          <h2>{title}</h2>
          <button className="icon-button" aria-label="닫기" onClick={onClose}>
            <X />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
export function CandidateCard({
  candidate: c,
  index,
  onDetail,
}: {
  candidate: Candidate;
  index: number;
  onDetail: () => void;
}) {
  return (
    <article className="candidate-card card">
      <div className="candidate-top">
        <div className={`ticker-icon ticker-${index % 4}`}>{c.ticker[0]}</div>
        <span className="candidate-rank">
          {String(index + 1).padStart(2, "0")} / SHORTLIST
        </span>
        <Badge tone="green">조건 충족 시 검토</Badge>
      </div>
      <div className="candidate-name">
        <h3>{c.name}</h3>
        <span>
          {c.ticker} · {c.exchange === "XNAS" ? "NASDAQ" : "NYSE"}
        </span>
      </div>
      <div className="candidate-price">
        {money(c.price)}
        <span
          className={(c.indicators.return5 ?? 0) >= 0 ? "positive" : "negative"}
        >
          {signed(c.indicators.return5 ?? 0, "%")}
          <small> 5일</small>
        </span>
      </div>
      <p className="candidate-reason">{c.reasons[0] ?? "확인 불가"}</p>
      <div className="candidate-pills">
        <Badge>{c.holding_days}거래일</Badge>
        <Badge>{sectors[c.sector]}</Badge>
        <Badge>적합도 {c.score}점</Badge>
      </div>
      <div className="price-triplet">
        <div>
          <span>조건부 진입</span>
          <strong>{money(c.entry)}</strong>
        </div>
        <div>
          <span>목표</span>
          <strong className="positive">{money(c.target)}</strong>
        </div>
        <div>
          <span>손절 기준</span>
          <strong className="negative">{money(c.stop)}</strong>
        </div>
      </div>
      <div className="candidate-risk">
        <TriangleAlert size={16} />
        <span>{c.risks.find((r) => !r.startsWith("합성")) ?? c.risks[0]}</span>
      </div>
      <button className="candidate-button" onClick={onDetail}>
        상세 분석 · 모의 투자하기
        <ArrowUpRight size={20} />
      </button>
    </article>
  );
}
export function Evidence({ candidate: c }: { candidate: Candidate }) {
  return (
    <>
      <h3>추천 근거</h3>
      <ul className="evidence-list">
        {c.reasons.length ? (
          c.reasons.map((r, i) => (
            <li key={i}>
              <span className="evidence-number">0{i + 1}</span>
              {r}
            </li>
          ))
        ) : (
          <li>확인 불가 · 필요한 데이터가 부족해요.</li>
        )}
      </ul>
      <h3>반대 근거와 위험</h3>
      <ul className="risk-list">
        {c.risks.map((r, i) => (
          <li key={i}>
            <TriangleAlert size={17} />
            {r}
          </li>
        ))}
      </ul>
      <p className="muted">
        원본: {c.source ?? "미연결"} · 규칙 {c.strategy_version}
        <br />
        근거 수준: {c.evidence} · 목표 달성 확률: 산출하지 않음
      </p>
      <details>
        <summary>계산 지표와 진입 규칙</summary>
        <div className="metric-grid">
          {Object.entries(c.indicators).map(([k, v]) => (
            <div key={k}>
              <span>
                {(
                  {
                    ma5: "5일 평균",
                    ma20: "20일 평균",
                    ma60: "60일 평균",
                    rsi: "RSI(14) 상대강도",
                    atr: "ATR(14) 변동폭",
                    volume_ratio: "거래량/20일 평균",
                    return5: "5일 수익률 %",
                    return10: "10일 수익률 %",
                    return20: "20일 수익률 %",
                    support: "20일 지지",
                    resistance: "20일 저항",
                  } as Record<string, string>
                )[k] ?? k}
              </span>
              <strong>{Number(v).toFixed(2)}</strong>
            </div>
          ))}
        </div>
        {Object.entries(c.rules ?? {}).map(([k, v]) => (
          <p key={k}>{String(v)}</p>
        ))}
      </details>
    </>
  );
}
export function TradeForm({
  candidate: c,
  research,
  cash,
  onSuccess,
}: {
  candidate: Candidate;
  research: Research;
  cash: number;
  onSuccess: () => Promise<void>;
}) {
  const [qty, setQty] = useState(Math.min(5, c.risk.quantity ?? 0)),
    [limit, setLimit] = useState(Number((c.entry * 1.003).toFixed(2))),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [key, setKey] = useState<string | null>(null),
    [locked, setLocked] = useState(false);
  const eligible =
    research.shortlist.includes(c.id) &&
    new Date(research.expires_at) > new Date();
  function change(fn: () => void) {
    if (locked) return;
    setKey(null);
    fn();
  }
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    const current = key ?? crypto.randomUUID();
    setKey(current);
    try {
      await api(
        "/orders",
        "POST",
        {
          instrument_id: c.id,
          side: "buy",
          mode: "demo-paper",
          quantity: qty,
          limit_price: limit,
          displayed_price: c.price,
          tolerance_pct: 0.5,
          research_id: research.id,
          order_type: "limit",
          session: "regular",
        },
        current,
      );
      await onSuccess();
    } catch (e) {
      setError((e as Error).message);
      setLocked(!(e instanceof HttpError) || e.status >= 500);
      if (e instanceof HttpError && e.status < 500) setKey(null);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="trade-panel">
      <Badge tone="blue">모의 투자 · 합성 호가</Badge>
      <h3>나의 진입 계획</h3>
      <p className="muted">
        현금 {money(cash)}
        <br />
        계산 수량 상한 {c.risk.quantity ?? 0}주
      </p>
      <form onSubmit={submit}>
        <label>
          매수 수량 (주)
          <input
            type="number"
            min={1}
            max={c.risk.quantity ?? 0}
            step={1}
            required
            value={qty}
            disabled={locked}
            onChange={(e) => change(() => setQty(Number(e.target.value)))}
          />
        </label>
        <label>
          또는 투자금 (USD)
          <input
            type="number"
            min={limit || 0.01}
            step="0.01"
            value={Number((qty * limit).toFixed(2)) || 0}
            disabled={locked}
            onChange={(e) =>
              change(() => setQty(Math.floor(Number(e.target.value) / limit)))
            }
          />
        </label>
        <label>
          지정가 (USD)
          <input
            type="number"
            min="0.01"
            step="0.01"
            required
            value={limit || ""}
            disabled={locked}
            onChange={(e) => change(() => setLimit(Number(e.target.value)))}
          />
        </label>
        <div className="trade-facts">
          <span>
            주문유형 <strong>지정가</strong>
          </span>
          <span>
            세션 <strong>데모 정규장</strong>
          </span>
          <span>
            가격 허용 범위 <strong>최대 0.5%</strong>
          </span>
          <span>
            예상 매수 비용 <strong>{money(qty * limit * 0.001)}</strong>
          </span>
          <span>
            예상 총액 <strong>{money(qty * limit * 1.001)}</strong>
          </span>
        </div>
        <div className="alert warning">
          <CircleHelp size={18} />
          <p>
            클릭 이후 합성 매도호가 + 5bp 슬리피지로 체결을 모의해요. 지정가
            이내에서 최대 3주씩 부분 체결될 수 있어요.
          </p>
        </div>
        {error && (
          <p className="error" role="alert">
            {error} 주문 기록을 먼저 확인하세요. 재시도는 동일 식별자를
            사용합니다.
          </p>
        )}
        <button
          className="primary"
          disabled={
            busy || !eligible || qty < 1 || qty > (c.risk.quantity ?? 0)
          }
        >
          {busy
            ? "접수 확인 중…"
            : locked
              ? "동일 주문 상태 확인"
              : "모의 투자 주문 제출"}
          <ArrowRight size={18} />
        </button>
        <p className="muted">
          계산 상한 수량 기준 계획 손실 {money(c.risk.planned_loss)} / 15% 하락
          스트레스 손실 {money(c.risk.stress_loss)}. 실제 손실은 이를 넘을 수
          있어요.
        </p>
        <p className="muted">실제 투자하기: 연결·권한 검증 전 비활성화</p>
      </form>
    </section>
  );
}
export function PositionCard({
  position: p,
  busy,
  onAnalyze,
  onSell,
}: {
  position: Position;
  busy: boolean;
  onAnalyze: () => void;
  onSell: () => void;
}) {
  return (
    <article className="card position-card">
      <div className="section-heading">
        <div className="position-name">
          <div className="ticker-icon">{p.ticker[0]}</div>
          <div>
            <h3>{p.name}</h3>
            <span className="muted">
              {p.ticker} · {p.quantity}주 · 모의 보유
            </span>
          </div>
        </div>
        <Badge tone={p.usable ? "green" : "amber"}>
          {p.usable ? "합성 호가 수신" : "데이터 부족 · 분석 제한"}
        </Badge>
      </div>
      <div className="position-main">
        <div>
          <span className="label">현재 체결가 기준 평가가격</span>
          <strong className="big-number">{money(p.quote?.last)}</strong>
          <p
            className={
              (p.valuation?.pnl_usd ?? 0) >= 0 ? "positive" : "negative"
            }
          >
            {money(p.valuation?.pnl_usd)} (
            {signed(p.valuation?.pnl_pct ?? 0, "%")})
          </p>
        </div>
        <div className="position-facts">
          <div>
            <span>체결 평균단가</span>
            <strong>{money(p.average_price)}</strong>
          </div>
          <div>
            <span>비용 차감 청산 추정 손익</span>
            <strong>{money(p.valuation?.liquidation_pnl_usd)}</strong>
          </div>
          <div>
            <span>KRW 평가손익 · 합성 환율</span>
            <strong>{money(p.valuation?.pnl_krw, "KRW")}</strong>
          </div>
          <div>
            <span>USD/KRW · 실제 환전 손익 아님</span>
            <strong>{p.quote?.quality.fx_usdkrw ?? "미연결"}</strong>
          </div>
        </div>
      </div>
      <div className="position-levels">
        <div>
          <span>최초 목표가까지</span>
          <strong className="positive">
            {p.quote
              ? signed((p.original.target / p.quote.last - 1) * 100, "%")
              : "확인 불가"}{" "}
            <small>({money(p.original.target)})</small>
          </strong>
        </div>
        <div>
          <span>최초 손절 기준까지</span>
          <strong className="negative">
            {p.quote
              ? signed((p.original.stop / p.quote.last - 1) * 100, "%")
              : "확인 불가"}{" "}
            <small>({money(p.original.stop)})</small>
          </strong>
        </div>
        <div>
          <span>보유 만료 · 데모 시간 기준</span>
          <DualTime value={p.original.holding_end} />
        </div>
      </div>
      <div className="position-bottom">
        <div>
          <span className="muted">최신 시세 수신</span>
          <DualTime value={p.quote?.collected_at} />
        </div>
        <div className="button-row">
          <button
            className="primary"
            disabled={busy || !p.usable}
            onClick={onAnalyze}
          >
            <Sparkles size={18} />
            분석하기
          </button>
          <button
            className="sell-button"
            disabled={busy || !p.usable}
            onClick={onSell}
          >
            일부 / 전량 모의 매도
          </button>
        </div>
      </div>
    </article>
  );
}
export function SellForm({
  position: p,
  onSuccess,
}: {
  position: Position;
  onSuccess: () => Promise<void>;
}) {
  const [qty, setQty] = useState(p.quantity),
    [limit, setLimit] = useState(
      Number(((p.quote?.bid ?? 0) * 0.998).toFixed(2)),
    ),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [key] = useState(() => crypto.randomUUID()),
    [locked, setLocked] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setLocked(true);
    setError("");
    try {
      await api(
        "/orders",
        "POST",
        {
          instrument_id: p.id,
          side: "sell",
          mode: "demo-paper",
          quantity: qty,
          limit_price: limit,
          displayed_price: p.quote?.last,
          tolerance_pct: 0.5,
          order_type: "limit",
          session: "regular",
        },
        key,
      );
      await onSuccess();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="sell-form" onSubmit={submit}>
      <Badge tone="amber">모의 매도 · 실제 주문 아님</Badge>
      <h3>
        {qty}주 · 예상 {money(qty * limit)}
      </h3>
      <p className="muted">
        현재 매수호가 {money(p.quote?.bid)} · 보유 {p.quantity}주
      </p>
      <label>
        매도 수량 (주)
        <input
          type="number"
          min={1}
          max={p.quantity}
          step={1}
          value={qty}
          disabled={locked}
          required
          onChange={(e) => setQty(Number(e.target.value))}
        />
      </label>
      <div className="button-row">
        <button
          type="button"
          className="secondary"
          disabled={locked}
          onClick={() => setQty(Math.max(1, Math.floor(p.quantity / 2)))}
        >
          절반 선택
        </button>
        <button
          type="button"
          className="secondary"
          disabled={locked}
          onClick={() => setQty(p.quantity)}
        >
          전량 선택
        </button>
      </div>
      <label>
        매도 지정가 (USD)
        <input
          type="number"
          step="0.01"
          min="0.01"
          value={limit}
          disabled={locked}
          required
          onChange={(e) => setLimit(Number(e.target.value))}
        />
      </label>
      <p className="muted">
        다음 합성 매수호가 − 5bp 슬리피지, 10bp 비용으로 체결을 모의해요. 지정가
        미충족 시 미체결로 남습니다.
      </p>
      {error && (
        <p className="error" role="alert">
          {error} 주문 기록을 먼저 확인하세요. 동일 식별자로만 재조회합니다.
        </p>
      )}
      <button className="sell-button full" disabled={busy}>
        {busy
          ? "접수 확인 중…"
          : locked
            ? "동일 매도 주문 상태 확인"
            : `${qty === p.quantity ? "전량" : "일부"} 모의 매도 주문 제출`}
      </button>
    </form>
  );
}
export function AnalysisCard({ job: j }: { job: Job }) {
  const r = j.result;
  return (
    <article className="card analysis-card">
      <div className="section-heading">
        <h3>보유 종목 재분석</h3>
        <Badge tone={r?.stale ? "amber" : "blue"}>
          {r?.stale ? "오래된 결과 · 재분석 필요" : statusLabel[j.state]}
        </Badge>
      </div>
      <p className="muted">
        {j.payload.instrument_id} · <DualTime value={j.created_at} />
      </p>
      {r && j.state === "completed" ? (
        <>
          <h2
            className={r.action.includes("매도") ? "warning-text" : "positive"}
          >
            {r.action}
          </h2>
          <h3>이전 분석 대비 변화</h3>
          {r.changes?.map((s: string) => <p key={s}>{s}</p>)}
          <details open>
            <summary>근거와 반대 근거</summary>
            {r.reasons?.map((s: string) => <p key={s}>+ {s}</p>)}
            {r.risks?.map((s: string) => (
              <p key={s} className="muted">
                △ {s}
              </p>
            ))}
          </details>
          <div className="alert info">
            <CircleHelp size={18} />
            <span>
              {r.conditions ?? "필수 데이터 확보 후 다시 분석하세요."}
            </span>
          </div>
          <p className="muted">
            최초 목표/손절 보존 · 자동 주문 없음
            <br />
            완료 <DualTime value={j.completed_at ?? undefined} />
            <br />
            유효기간 30초 · 뉴스·공시·분봉 미확보
          </p>
        </>
      ) : (
        <p role="status">
          {j.state === "failed"
            ? r?.error
            : "워커가 일봉·호가·시장·업종과 보유 상태를 같은 스냅샷으로 묶고 있어요."}
        </p>
      )}
    </article>
  );
}
export function Backtest({
  jobs,
  research,
  busy,
  onRun,
}: {
  jobs: Job[];
  research: Research | null;
  busy: boolean;
  onRun: (id: string, days: number) => void;
}) {
  const [id, setId] = useState(research?.candidates[0]?.id ?? "cik:0000320193"),
    [days, setDays] = useState(7);
  return (
    <>
      <section className="card">
        <Badge tone="amber">과거 검증 · 합성 데이터 실험</Badge>
        <h2>전략 검증은 아직 완료되지 않았어요</h2>
        <p className="muted">
          엔진 동작을 확인하는 가격 전략 실험이에요. 실제 장기 데이터·과거
          구성종목·상장폐지 이력이 없으며 미래의 목표 달성 확률을 추정하지
          않아요.
        </p>
        <div className="backtest-form">
          <label>
            종목
            <select value={id} onChange={(e) => setId(e.target.value)}>
              {(
                research?.candidates ?? [
                  { id: "cik:0000320193", ticker: "AAPL" },
                ]
              ).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.ticker}
                </option>
              ))}
            </select>
          </label>
          <label>
            보유 거래일
            <input
              type="number"
              min={2}
              max={20}
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
            />
          </label>
          <button
            className="primary"
            disabled={busy || days < 2 || days > 20}
            onClick={() => onRun(id, days)}
          >
            가격 전략 실험 실행
          </button>
        </div>
      </section>
      {jobs.map((j) => (
        <section className="card" key={j.id}>
          <div className="section-heading">
            <h3>최종 평가 구간 결과</h3>
            <Badge>{statusLabel[j.state]}</Badge>
          </div>
          {j.result && j.state === "completed" ? (
            <>
              <p>{j.result.validation}</p>
              <p className="muted">
                {j.result.period.join(" ~ ")} · {j.result.scope}
              </p>
              <div className="metric-grid">
                {[
                  ["수익률", signed(j.result.return_pct, "%")],
                  ["최대 낙폭", signed(j.result.max_drawdown_pct, "%")],
                  ["거래 수", `${j.result.trades_count}회`],
                  [
                    "승률",
                    j.result.win_rate === null
                      ? "표본 없음"
                      : `${(j.result.win_rate * 100).toFixed(1)}%`,
                  ],
                  [
                    "평균 이익 / 손실",
                    `${money(j.result.average_win)} / ${money(j.result.average_loss)}`,
                  ],
                  [
                    "목표 선도달",
                    j.result.target_first_rate === null
                      ? "표본 없음"
                      : `${(j.result.target_first_rate * 100).toFixed(1)}%`,
                  ],
                  ["보유 만료", `${j.result.expiry_count}회`],
                  ["회전율", `${j.result.turnover.toFixed(2)}배`],
                  ["매수·보유 비교", signed(j.result.baseline_return_pct, "%")],
                  ["시장 대비 성과", "실제 지수 미연결"],
                ].map(([label, value]) => (
                  <div key={label}>
                    <span>{label}</span>
                    <strong>{value}</strong>
                  </div>
                ))}
              </div>
              <p className="muted">
                목표 선도달 빈도 95% Wilson 구간:{" "}
                {j.result.target_first_wilson_95
                  ?.map((n: number) => (n * 100).toFixed(1) + "%")
                  .join(" ~ ") ?? "표본 없음"}{" "}
                · 미래 확률 아님
              </p>
              <details>
                <summary>평가 분리와 체결 가정</summary>
                <p>
                  시간순 개발 60% / 검증 20% / 최종 평가 20%, 경계에{" "}
                  {j.result.splits.purge_sessions}세션 간격. 가중치 최적화 없음.
                </p>
                {Object.entries(j.result.partition_results ?? {}).map(
                  ([key, value]) => (
                    <p key={key}>
                      {key}: {(value as Json).trades_count}회 ·{" "}
                      {signed((value as Json).return_pct, "%")}
                    </p>
                  ),
                )}
                {j.result.assumptions.map((a: string) => (
                  <p key={a}>{a}</p>
                ))}
              </details>
            </>
          ) : (
            <p role="status">
              {j.state === "failed"
                ? j.result?.error
                : "워커에서 실험을 실행하고 있어요…"}
            </p>
          )}
        </section>
      ))}
    </>
  );
}
export function SettingsForm({
  initial,
  candidates,
  busy,
  onSave,
}: {
  initial: Preferences;
  candidates: Candidate[];
  busy: boolean;
  onSave: (p: Preferences) => void;
}) {
  const [p, setP] = useState(initial);
  function value<K extends keyof Preferences>(key: K, value: Preferences[K]) {
    setP((old) => ({ ...old, [key]: value }));
  }
  return (
    <form
      className="card settings-form"
      onSubmit={(e) => {
        e.preventDefault();
        const { budget_usd, ...rest } = p;
        onSave(rest);
      }}
    >
      <div className="section-heading">
        <h2>투자 조건</h2>
        <Badge>사용 예시 · 미검증</Badge>
      </div>
      <div className="form-grid">
        <label>
          보유 기간
          <select
            value={
              p.holding_days <= 5
                ? "short"
                : p.holding_days <= 10
                  ? "medium"
                  : "long"
            }
            onChange={(e) =>
              value(
                "holding_days",
                e.target.value === "short"
                  ? 5
                  : e.target.value === "medium"
                    ? 7
                    : 15,
              )
            }
          >
            <option value="short">2~5거래일 · 단기 추세</option>
            <option value="medium">6~10거래일 · 추세 지속</option>
            <option value="long">11~20거래일 · 중기 구조</option>
          </select>
        </label>
        <label>
          직접 입력 (2~20거래일)
          <input
            type="number"
            min={2}
            max={20}
            step={1}
            value={p.holding_days}
            required
            onChange={(e) => value("holding_days", Number(e.target.value))}
          />
        </label>
        <label>
          목표 순수익률 (%)
          <input
            type="number"
            min="0.01"
            max={100}
            step="0.01"
            value={p.target_pct}
            required
            onChange={(e) => value("target_pct", Number(e.target.value))}
          />
        </label>
        <label>
          투자금 통화
          <select
            value={p.currency}
            onChange={(e) => value("currency", e.target.value as "USD" | "KRW")}
          >
            <option value="USD">미국 달러 USD</option>
            <option value="KRW">대한민국 원 KRW · 합성 환율</option>
          </select>
        </label>
        <label>
          투자 예산 ({p.currency})
          <input
            type="number"
            min={1}
            max={1000000000}
            step="0.01"
            value={p.budget}
            required
            onChange={(e) => value("budget", Number(e.target.value))}
          />
        </label>
        <label>
          거래당 손실 예산 (USD)
          <input
            type="number"
            min="0.01"
            max={1000000}
            step="0.01"
            value={p.loss_budget_usd}
            required
            onChange={(e) => value("loss_budget_usd", Number(e.target.value))}
          />
        </label>
        <label>
          종목당 최대 비중 (%)
          <input
            type="number"
            min={1}
            max={100}
            value={Number((p.max_weight * 100).toFixed(2))}
            required
            onChange={(e) => value("max_weight", Number(e.target.value) / 100)}
          />
        </label>
        <label>
          최대 보유 종목 수
          <input
            type="number"
            min={1}
            max={20}
            step={1}
            value={p.max_positions}
            required
            onChange={(e) => value("max_positions", Number(e.target.value))}
          />
        </label>
      </div>
      <details>
        <summary>외부 보유 종목을 위험 한도에 반영 (선택)</summary>
        <p className="muted">
          외부 보유는 집중도 계산에 반영하며 모의 체결과 구분합니다. 실제 계좌와
          자동 대사하지 않아요.
        </p>
        {p.existing_holdings.map((holding, index) => (
          <div className="holding-input" key={index}>
            <label>
              종목
              <select
                value={holding.instrument_id}
                onChange={(e) =>
                  value(
                    "existing_holdings",
                    p.existing_holdings.map((h, i) =>
                      i === index ? { ...h, instrument_id: e.target.value } : h,
                    ),
                  )
                }
              >
                {candidates.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.ticker}
                  </option>
                ))}
              </select>
            </label>
            <label>
              보유 수량
              <input
                type="number"
                min={1}
                max={100000}
                required
                value={holding.quantity}
                onChange={(e) =>
                  value(
                    "existing_holdings",
                    p.existing_holdings.map((h, i) =>
                      i === index
                        ? { ...h, quantity: Number(e.target.value) }
                        : h,
                    ),
                  )
                }
              />
            </label>
            <button
              type="button"
              className="secondary"
              onClick={() =>
                value(
                  "existing_holdings",
                  p.existing_holdings.filter((_, i) => i !== index),
                )
              }
            >
              제거
            </button>
          </div>
        ))}
        <button
          type="button"
          className="secondary"
          disabled={!candidates.length || p.existing_holdings.length >= 20}
          onClick={() =>
            value("existing_holdings", [
              ...p.existing_holdings,
              { instrument_id: candidates[0].id, quantity: 1 },
            ])
          }
        >
          외부 보유 종목 추가
        </button>
      </details>
      <div className="alert warning">
        <TriangleAlert size={20} />
        <span>
          손실 예산은 실제 손실 상한이 아닙니다. 갭 하락·거래정지로 계획한
          손절가에 팔리지 않을 수 있어요.
        </span>
      </div>
      <p className="muted">
        모의 시작 현금은 $10,000이며 투자 예산은 주문당 한도입니다. 업종별 50%
        한도를 추가로 적용해요.
      </p>
      <button className="primary" disabled={busy}>
        {busy ? "저장 중…" : "투자 기준 저장"}
        <Check size={20} />
      </button>
    </form>
  );
}
