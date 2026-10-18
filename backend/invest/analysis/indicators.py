"""All calculations use numeric OHLCV, not chart images. See docs/METHODOLOGY.md."""

import numpy as np
import pandas as pd

REQUIRED = ["open", "high", "low", "close", "volume"]


def validate_bars(frame: pd.DataFrame, minimum: int = 60) -> list[str]:
    errors = []
    if len(frame) < minimum:
        errors.append(f"이력 부족: 최소 {minimum}개 완성 일봉")
    if any(c not in frame for c in REQUIRED):
        return errors + ["OHLCV 필수 필드 누락"]
    a = frame[REQUIRED]
    if not np.isfinite(a.to_numpy(dtype=float)).all():
        errors.append("결측 또는 비정상 가격")
    if (a[["open", "high", "low", "close"]] <= 0).any().any() or (a.volume <= 0).any():
        errors.append("가격 또는 거래량이 0 이하")
    if (
        (frame.high < frame[["open", "close", "low"]].max(axis=1))
        | (frame.low > frame[["open", "close", "high"]].min(axis=1))
    ).any():
        errors.append("OHLC 가격 조정 오류")
    if "session" in frame and (frame.session.duplicated().any() or not frame.session.is_monotonic_increasing):
        errors.append("일봉 시각 중복 또는 순서 오류")
    return errors


def wilder(series: pd.Series, period: int, start: int = 0) -> pd.Series:
    result = pd.Series(np.nan, index=series.index, dtype=float)
    seed = start + period - 1
    if len(series) <= seed:
        return result
    result.iloc[seed] = series.iloc[start : seed + 1].mean()
    for i in range(seed + 1, len(series)):
        result.iloc[i] = (result.iloc[i - 1] * (period - 1) + series.iloc[i]) / period
    return result


def indicators(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    close = frame.close.astype(float)
    for n in [5, 20, 60]:
        result[f"ma{n}"] = close.rolling(n, min_periods=n).mean()
    for n in [5, 10, 20]:
        result[f"return{n}"] = close.pct_change(n, fill_method=None) * 100
    result["volume_ratio"] = frame.volume / frame.volume.rolling(20, min_periods=20).mean()
    delta = close.diff()
    gains, losses = wilder(delta.clip(lower=0), 14, 1), wilder(-delta.clip(upper=0), 14, 1)
    result["rsi"] = 100 - 100 / (1 + gains / losses.replace(0, np.nan))
    result.loc[(losses == 0) & (gains > 0), "rsi"] = 100
    result.loc[(losses == 0) & (gains == 0), "rsi"] = 50
    true_range = pd.concat(
        [frame.high - frame.low, (frame.high - close.shift()).abs(), (frame.low - close.shift()).abs()],
        axis=1,
    ).max(axis=1)
    result["atr"] = wilder(true_range, 14)
    result["support"] = frame.low.rolling(20, min_periods=20).min()
    result["resistance"] = frame.high.rolling(20, min_periods=20).max()
    return result


def align_relative(stock: pd.DataFrame, benchmark: pd.DataFrame, days: int) -> float | None:
    aligned = (
        stock.set_index("session")
        .close.to_frame("stock")
        .join(benchmark.set_index("session").close.rename("benchmark"), how="inner")
    )
    if len(aligned) < days + 1 or aligned.index[-1] != stock.session.iloc[-1]:
        return None
    returns = (aligned.iloc[-1] / aligned.iloc[-days - 1] - 1) * 100
    return float(returns.stock - returns.benchmark)
