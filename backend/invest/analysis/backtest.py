"""Price-only, long-only, single-security experiment. Not a portfolio backtest.

Signals use completed, available bars; first entry is on the following session.
There is no news contribution and no claims about real historical performance.
"""

import math

import numpy as np
import pandas as pd

from .indicators import indicators, validate_bars
from .selection import strategy_for
from .risk import fee, D, SLIPPAGE_BPS, COST_VERSION


def exit_for_bar(bar, stop, target):
    # Intrabar ordering is unknown: a touched stop wins any target conflict.
    if bar["open"] <= stop:
        return float(bar["open"]), "stop_gap"
    if bar["low"] <= stop:
        return float(stop), "stop_first_conservative"
    if bar["open"] >= target:
        return float(target), "target_gap_conservative"
    if bar["high"] >= target:
        return float(target), "target_first"
    return None, None


def time_splits(length: int, holding_days: int):
    a, b = int(length * 0.6), int(length * 0.8)
    return {
        "development": [60, a - holding_days],
        "validation": [a, b - holding_days],
        "final": [b, length],
        "purge_sessions": holding_days,
        "walk_forward": [[60, a - holding_days, a, b - holding_days], [60, b - holding_days, b, length]],
        "rule_tuned": False,
    }


def run_backtest(bars: list[dict], holding_days=7, initial_cash=10000.0, start=None, end=None):
    frame = pd.DataFrame(bars)
    errors = validate_bars(frame, 120)
    if errors:
        raise ValueError("; ".join(errors))
    for row in bars:
        if not row.get("available_at") or not row.get("observed_at"):
            raise ValueError("이용 가능 시각 없는 봉은 검증에 사용할 수 없습니다.")
        if row.get("adjustment_factor", 1) != 1:
            raise ValueError("기업행동 이력이 포함된 실데이터는 별도 PIT 조정 검증 후 사용하세요.")
    data = indicators(frame)
    _, strategy = strategy_for(holding_days)
    first, last = max(60, start or 60), min(end or len(data), len(data))
    if last - first < holding_days + 2:
        raise ValueError("평가 구간이 너무 짧습니다.")
    cash, position, pending = initial_cash, None, None
    trades, curve, daily_returns = [], [initial_cash], []
    for i in range(first, last):
        bar = data.iloc[i]
        available = pd.Timestamp(bar.available_at)
        if available > pd.Timestamp(bar.observed_at):
            # This candle cannot be used as an end-of-session signal yet. Prior position
            # management still uses tradable bar prices in the simulator.
            can_signal = False
        else:
            can_signal = True
        if bar.get("halted", False):
            curve.append(cash + (position["quantity"] * bar.close if position else 0))
            continue
        if pending and not position:
            if bar.open <= pending["limit"] and bar.open > pending["stop"]:
                fill = float(bar.open) * (1 + float(SLIPPAGE_BPS) / 10000)
                if fill <= pending["limit"]:
                    quantity = int(cash * 0.25 / (fill * 1.001))
                    if quantity > 0:
                        entry_fee = float(fee(fill, quantity))
                        cash -= fill * quantity + entry_fee
                        position = {
                            **pending,
                            "entry": fill,
                            "quantity": quantity,
                            "entry_index": i,
                            "entry_session": bar.session,
                            "entry_fee": entry_fee,
                        }
            # Conservative: daily low crossing a limit does not establish available ask liquidity.
            pending = None
        if position:
            exit_price, reason = exit_for_bar(bar, position["stop"], position["target"])
            if exit_price is None and i - position["entry_index"] + 1 >= holding_days:
                exit_price, reason = float(bar.close), "holding_expiry"
            if exit_price is None and i == last - 1:
                exit_price, reason = float(bar.close), "evaluation_end"
            if exit_price is not None:
                exit_price *= 1 - float(SLIPPAGE_BPS) / 10000
                exit_fee = float(fee(exit_price, position["quantity"], "sell"))
                proceeds = exit_price * position["quantity"] - exit_fee
                cash += proceeds
                cost = position["entry"] * position["quantity"] + position["entry_fee"]
                trades.append(
                    {
                        **position,
                        "exit": exit_price,
                        "exit_session": bar.session,
                        "reason": reason,
                        "pnl": proceeds - cost,
                        "return_pct": (proceeds / cost - 1) * 100,
                        "exit_fee": exit_fee,
                    }
                )
                position = None
        if not position and i < last - 1 and can_signal:
            # Complete history up to and including i; all windows are backward-looking.
            close = float(bar.close)
            if close > bar.ma20 > bar.ma60 and 35 <= bar.rsi <= 72:
                stop = max(float(bar.support), close - strategy["stop_atr"] * float(bar.atr))
                target = min(float(bar.resistance), close + strategy["target_atr"] * float(bar.atr))
                if stop < close < target and (target - close) / (close - stop) >= 1.1:
                    pending = {
                        "limit": close * 1.005,
                        "stop": stop,
                        "target": target,
                        "signal_index": i,
                        "signal_session": bar.session,
                        "signal_available_at": bar.available_at,
                    }
        equity = cash + (position["quantity"] * float(bar.close) if position else 0)
        daily_returns.append(equity / curve[-1] - 1)
        curve.append(equity)
    # A halt at the end may leave a position unliquidated; disclose the marked value explicitly.
    equity = curve[-1]
    values = np.array(curve)
    drawdown = (values / np.maximum.accumulate(values) - 1) * 100
    wins = [t["pnl"] for t in trades if t["pnl"] > 0]
    losses = [t["pnl"] for t in trades if t["pnl"] <= 0]
    target_count = sum(t["reason"].startswith("target") for t in trades)
    n = len(trades)
    phat = target_count / n if n else 0
    z = 1.96
    if n:
        middle = (phat + z * z / (2 * n)) / (1 + z * z / n)
        margin = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / (1 + z * z / n)
        interval = [max(0, middle - margin), min(1, middle + margin)]
    else:
        interval = None
    # Same cash, 25% allocation, same endpoints/costs/slippage; remaining capital stays cash.
    buy = float(data.iloc[first].open) * 1.0005
    sell = float(data.iloc[last - 1].close) * 0.9995
    qty = int(initial_cash * 0.25 / (buy * 1.001))
    baseline = (
        ((sell - buy) * qty - float(fee(buy, qty)) - float(fee(sell, qty, "sell"))) / initial_cash * 100
    )
    return {
        "mode": "backtest",
        "dataset": "합성 데이터 가격 전략 실험",
        "validation": "검증 미완료 · 실제 장기 데이터 없음",
        "scope": "단일 종목 + 현금 · 전체 포트폴리오 아님",
        "strategy_version": "hypothesis-v1",
        "cost_version": COST_VERSION,
        "period": [str(data.iloc[first].session), str(data.iloc[last - 1].session)],
        "return_pct": (equity / initial_cash - 1) * 100,
        "max_drawdown_pct": float(drawdown.min()),
        "trades_count": n,
        "win_rate": len(wins) / n if n else None,
        "average_win": float(np.mean(wins)) if wins else None,
        "average_loss": float(np.mean(losses)) if losses else None,
        "target_first_rate": phat if n else None,
        "target_first_wilson_95": interval,
        "expiry_count": sum(t["reason"] == "holding_expiry" for t in trades),
        "turnover": sum(t["quantity"] * (t["entry"] + t["exit"]) for t in trades) / initial_cash,
        "baseline_return_pct": baseline,
        "excess_vs_buy_hold_pct": (equity / initial_cash - 1) * 100 - baseline,
        "market_excess_return_pct": None,
        "unliquidated_quantity": position["quantity"] if position else 0,
        "trades": trades,
        "equity_curve": curve,
        "splits": time_splits(len(data), holding_days),
        "assumptions": [
            "당일 종가 신호 → 다음 거래일 시가가 지정가 이내일 때만 진입",
            "일봉 내 목표/손절 동시 도달은 손절 우선, 손절 갭은 시가 적용",
            "수수료 편도 10bp·슬리피지 편도 5bp·매도세 0bp는 시연 가정",
            "현재 생존한 예시 종목만 사용 · 상장폐지·과거 구성종목·실제 유동성 미확보",
            "뉴스·공시·사건 정보 미포함 · 뉴스 결합 전략 성과 아님",
        ],
    }


def split_position(quantity, average_price, ratio):
    if ratio <= 0 or quantity < 0:
        raise ValueError("Invalid split")
    new_quantity = D(quantity) * D(ratio)
    if new_quantity != int(new_quantity):
        raise ValueError("Fractional cash-in-lieu requires a verified corporate action feed")
    return int(new_quantity), float(D(average_price) / D(ratio))
