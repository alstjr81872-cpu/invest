import { useState, type FormEvent } from "react";
import { ArrowRight, ShieldCheck } from "lucide-react";
import { api, setCsrf } from "./api";
import { Logo, Badge } from "./components";
export default function Login({ onLogin }: { onLogin: () => void }) {
  const [username, setUsername] = useState("owner"),
    [password, setPassword] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await api<{ csrf: string }>("/login", "POST", {
        username,
        password,
      });
      setCsrf(result.csrf);
      setPassword("");
      onLogin();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="login-page">
      <div className="login-intro">
        <Logo />
        <Badge tone="blue">
          <ShieldCheck size={16} /> 비공개 투자 연구실
        </Badge>
        <h1>
          수익의 약속보다,
          <br />
          <span>판단의 근거를.</span>
        </h1>
        <p>
          가격의 흐름을 읽고, 위험을 먼저 확인하세요.
          <br />
          나만의 기준으로 다음 투자를 준비하는 공간.
        </p>
        <div className="login-art" aria-hidden="true">
          <div className="art-grid" />
          <svg viewBox="0 0 600 190">
            <defs>
              <linearGradient id="area" x1="0" y1="0" x2="0" y2="1">
                <stop stopColor="#3182f6" stopOpacity=".26" />
                <stop offset="1" stopColor="#3182f6" stopOpacity="0" />
              </linearGradient>
            </defs>
            <path
              d="M0 155 L30 148 L65 160 L100 120 L140 135 L175 92 L210 101 L245 80 L280 100 L320 51 L355 72 L395 40 L430 60 L470 25 L510 38 L550 8 L600 20 L600 190 L0 190 Z"
              fill="url(#area)"
            />
            <path
              d="M0 155 L30 148 L65 160 L100 120 L140 135 L175 92 L210 101 L245 80 L280 100 L320 51 L355 72 L395 40 L430 60 L470 25 L510 38 L550 8 L600 20"
              fill="none"
              stroke="#5c9efa"
              strokeWidth="3"
            />
          </svg>
          <span>시연용 일러스트 · 실제 시세 아님</span>
        </div>
      </div>
      <section className="login-card card">
        <span className="eyebrow">WELCOME BACK</span>
        <h2>나의 연구실에 로그인</h2>
        <p className="muted">소유자 한 명만 사용하는 비공개 계정이에요.</p>
        <form onSubmit={submit}>
          <label>
            계정
            <input
              name="username"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </label>
          <label>
            비밀번호
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <button className="primary" disabled={busy}>
            {busy ? "로그인 중…" : "로그인"}
            <ArrowRight size={20} />
          </button>
        </form>
        <div className="login-foot">
          <ShieldCheck size={20} />
          <span>
            회원가입 없이 서버 환경에서 계정을 설정해요.
            <br />
            모의 투자가 기본이며 실제 주문은 비활성화돼요.
          </span>
        </div>
      </section>
      <p className="login-disclaimer">
        투자 판단을 돕는 연구 도구입니다. 수익을 보장하지 않습니다.
      </p>
    </main>
  );
}
