"""Deterministic synthetic daily histories and changing synthetic level-one quotes."""

from datetime import datetime
import hashlib
import math

import numpy as np

from ..calendar import completed_sessions, nyse, demo_clock

UNIVERSE = [
    ("cik:0000320193", "AAPL", "XNAS", "Apple", "technology", 214),
    ("cik:0000789019", "MSFT", "XNAS", "Microsoft", "technology", 428),
    ("cik:0001045810", "NVDA", "XNAS", "NVIDIA", "technology", 132),
    ("cik:0001018724", "AMZN", "XNAS", "Amazon", "consumer", 194),
    ("cik:0000019617", "JPM", "XNYS", "JPMorgan Chase", "financials", 243),
    ("cik:0000200406", "JNJ", "XNYS", "Johnson & Johnson", "healthcare", 162),
]
BENCHMARKS = [
    ("demo:sp500", "DEMO-SPX", "XNYS", "S&P 500 형태 합성 지수", "index", 5700),
    ("demo:technology", "DEMO-TECH", "XNYS", "기술 업종 합성 기준", "index", 800),
    ("demo:consumer", "DEMO-CONS", "XNYS", "소비 업종 합성 기준", "index", 800),
    ("demo:financials", "DEMO-FIN", "XNYS", "금융 업종 합성 기준", "index", 800),
    ("demo:healthcare", "DEMO-HEALTH", "XNYS", "헬스케어 합성 기준", "index", 800),
]


def history(identifier: str, reference: float, now: datetime, count=420) -> list:
    seed = int(hashlib.sha256(identifier.encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    sessions = completed_sessions(demo_clock(now), count)
    t = np.arange(count)
    drift = 0.00055 if identifier.startswith("demo:") else 0.0012
    # The last period pulls back inside an upward structure; not fitted to a real security.
    close = reference * np.exp(
        drift * (t - count + 1) + 0.016 * np.sin((t - count + 1) / 4) + rng.normal(0, 0.0025, count)
    )
    close *= reference / close[-1]
    opening = np.r_[close[0], close[:-1]] * (1 + rng.normal(0, 0.0015, count))
    high = np.maximum(opening, close) * (1 + rng.uniform(0.006, 0.013, count))
    # Explicit demo scenario: a past upper wick supplies room below resistance.
    # This fixture is not market history and is never used as proof of strategy performance.
    high[-12] *= 1.065
    low = np.minimum(opening, close) * (1 - rng.uniform(0.006, 0.013, count))
    volume = rng.integers(8_000_000, 18_000_000, count)
    volume[-1] = 21_000_000
    cal = nyse()
    return [
        {
            "session": str(s.date()),
            "open": round(float(opening[i]), 4),
            "high": round(float(high[i]), 4),
            "low": round(float(low[i]), 4),
            "close": round(float(close[i]), 4),
            "volume": int(volume[i]),
            "turnover": round(float(close[i] * volume[i]), 2),
            "observed_at": cal.session_close(s).isoformat(),
            "collected_at": now.isoformat(),
            "available_at": cal.session_close(s).isoformat(),
            "source": "synthetic-v1",
            "adjusted": True,
            "adjustment_factor": 1.0,
        }
        for i, s in enumerate(sessions)
    ]


def quote(identifier: str, reference: float, now: datetime) -> dict:
    phase = int(hashlib.sha256(identifier.encode()).hexdigest()[:4], 16) / 100
    last = round(reference * (1 + 0.0015 * math.sin(now.timestamp() / 15 + phase)), 2)
    return {
        "last": last,
        "bid": round(last - 0.02, 2),
        "ask": round(last + 0.02, 2),
        "observed_at": now,
        "collected_at": now,
        "available_at": now,
        "sequence": int(now.timestamp() * 1000),
        "source": "synthetic-v1",
        "quality": {
            "connection": "connected",
            "delay_seconds": 0,
            "halt_clear": True,
            "warning_clear": True,
            "corporate_actions_clear": True,
            "events_clear": True,
            "demo": True,
            "session": "regular",
            "ask_size": 3,
            "bid_size": 3,
            "simulation_time": demo_clock(now).isoformat(),
            "fx_usdkrw": 1350.0,
            "disclaimer": "데모 데이터 · 합성 호가 · 실제 시장 아님",
        },
    }
