from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
import math


def D(n):
    return Decimal(str(n))


# These are disclosed simulation assumptions, NOT verified current broker/tax rates.
COMMISSION_BPS = D("10")
SLIPPAGE_BPS = D("5")
SELL_TAX_BPS = D("0")
COST_VERSION = "demo-assumptions-v1"


def cents(n):
    return D(n).quantize(D("0.01"), rounding=ROUND_HALF_UP)


def fee(price, quantity, side="buy"):
    return D(price) * quantity * (COMMISSION_BPS + (SELL_TAX_BPS if side == "sell" else 0)) / 10000


def size_position(
    *,
    entry,
    stop,
    target,
    cash,
    equity,
    budget,
    max_weight,
    loss_budget,
    existing_value=0,
    sector_value=0,
    max_sector_weight=0.5,
):
    entry, stop, target = map(D, (entry, stop, target))
    if not (0 < stop < entry < target):
        return {"quantity": 0, "reason": "가격 구조 부적합"}
    slippage = entry * SLIPPAGE_BPS / 10000
    loss_per = entry - stop + fee(entry, 1) + fee(stop, 1, "sell") + slippage * 2
    gain_per = target - entry - fee(entry, 1) - fee(target, 1, "sell") - slippage * 2
    per_cost = entry + fee(entry, 1) + slippage
    allocation = max(
        D(0),
        min(
            D(cash),
            D(budget),
            D(equity) * D(max_weight) - D(existing_value),
            D(equity) * D(max_sector_weight) - D(sector_value),
        ),
    )
    quantity = int(
        min(allocation / per_cost, D(loss_budget) / loss_per).to_integral_value(rounding=ROUND_FLOOR)
    )
    return {
        "quantity": quantity,
        "planned_loss": float(loss_per * quantity),
        "stress_loss": float((entry * D("0.15") + fee(entry, 1) * 2) * quantity),
        "risk_reward": round(float(gain_per / loss_per), 3),
        "net_gain_pct": float(gain_per / entry * 100),
        "cost_version": COST_VERSION,
        "reason": "손실 예산은 실제 손실 상한이 아닙니다. 갭·거래정지 시 초과할 수 있습니다.",
    }


def value_position(quantity, average, last, bid, entry_fee, entry_fx, current_fx):
    base = D(average) * quantity + D(entry_fee)
    mark = D(last) * quantity
    liquidation = None if bid is None else D(bid) * quantity - fee(bid, quantity, "sell")
    return {
        "market_value_usd": float(mark),
        "pnl_usd": float(mark - base),
        "pnl_pct": float((mark - base) / base * 100) if base else 0,
        "liquidation_pnl_usd": None if liquidation is None else float(liquidation - base),
        "pnl_krw": float(mark * D(current_fx) - base * D(entry_fx)),
        "fx_component_krw": float(mark * (D(current_fx) - D(entry_fx))),
        "fx_kind": "합성 환율 평가손익 · 실제 환전 손익 아님",
    }


def finite_number(value):
    return isinstance(value, (int, float)) and math.isfinite(value)
