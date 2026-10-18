"""Cash-only limit paper orders. Every mutation locks the account first.

Never dispatch external orders through a retryable paper job. A broker timeout belongs in
needs_review and must be reconciled before any further transmission.
"""

import hashlib
import json
from datetime import timedelta, datetime

from sqlalchemy import select, func

from .models import Account, Order, Position, Quote, Recommendation, Fill
from .db import utcnow
from .config import settings
from .calendar import session_info, demo_clock, holding_end
from .service import OPEN_ORDERS, portfolio, preferences, quote_dict, emit, exposure
from .providers.base import quote_usable
from .analysis.risk import D, cents, fee, SLIPPAGE_BPS, size_position


class OrderRejected(ValueError):
    pass


def lock_account(db):
    return db.scalar(select(Account).where(Account.id == 1).with_for_update())


def submit(db, request: dict, key: str):
    account = lock_account(db)
    digest = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
    existing = db.scalar(select(Order).where(Order.idempotency_key == key))
    if existing:
        if existing.request_hash != digest:
            raise OrderRejected("같은 주문 식별자를 다른 주문에 사용할 수 없습니다.")
        return existing
    if request["mode"] != "demo-paper" or settings().data_mode != "demo":
        raise OrderRejected("실제 주문과 실제 시세 기반 체결은 연결 검증 전까지 비활성화되어 있습니다.")
    now = utcnow()
    item_id = request["instrument_id"]
    quantity, side = request["quantity"], request["side"]
    limit = D(request["limit_price"])
    if quantity <= 0 or limit <= 0 or limit != cents(limit):
        raise OrderRejected("양의 정수 수량과 0.01 USD 호가단위를 사용하세요.")
    q = quote_dict(db.get(Quote, item_id))
    valid, reason = quote_usable(q, now)
    if not valid:
        raise OrderRejected("시세 부적합: " + reason)
    if session_info(demo_clock(now))["state"] != "regular":
        raise OrderRejected("정규장 세션이 아닙니다.")
    display = D(request["displayed_price"])
    tolerance = min(D(request.get("tolerance_pct", 0.5)), D("0.5")) / 100
    if display <= 0 or abs(D(q["last"]) / display - 1) > tolerance:
        raise OrderRejected("표시 이후 가격이 허용 범위를 벗어났습니다. 새 가격을 확인하세요.")
    pf, prefs = portfolio(db), preferences(db)
    pos = db.get(Position, item_id)
    if side == "buy":
        if any(
            q["quality"].get(field) is not True
            for field in ["warning_clear", "corporate_actions_clear", "events_clear"]
        ):
            raise OrderRejected("필수 위험 항목이 변경되었거나 확인되지 않았습니다.")
        funds = exposure(db, item_id, pf, prefs)
        if funds["missing"] or not pf["valuation_complete"]:
            raise OrderRejected("기존 보유 종목의 평가 데이터가 부족합니다.")
        research = db.get(Recommendation, request.get("research_id"))
        if not research or research.expires_at <= now or research.payload["mode"] != "demo":
            raise OrderRejected("추천 유효기간이 지났습니다. 다시 분석하세요.")
        if research.payload["settings"] != prefs:
            raise OrderRejected("설정이 변경되었습니다. 추천을 다시 계산하세요.")
        c = next((c for c in research.payload["candidates"] if c["id"] == item_id), None)
        if not c or item_id not in research.payload["shortlist"]:
            raise OrderRejected("진입 조건을 통과한 후보가 아닙니다.")
        if (pos and pos.quantity > 0) or funds["existing_value"]:
            raise OrderRejected("추가 매수는 지원하지 않습니다.")
        pending_buys = list(
            db.scalars(select(Order).where(Order.side == "buy", Order.status.in_(OPEN_ORDERS)))
        )
        if any(o.instrument_id == item_id for o in pending_buys):
            raise OrderRejected("동일 종목의 매수 대기 주문이 있습니다.")
        if funds["count"] >= prefs["max_positions"]:
            raise OrderRejected("최대 보유 종목 수에 도달했습니다.")
        if limit > D(c["entry"]) * D("1.005") or D(q["ask"]) > D(c["entry"]) * D("1.005"):
            raise OrderRejected("추격 금지 가격 범위를 벗어났습니다.")
        risk = size_position(
            entry=limit,
            stop=c["stop"],
            target=c["target"],
            cash=pf["available_cash"],
            equity=funds["equity"],
            budget=prefs["budget_usd"],
            max_weight=prefs["max_weight"],
            loss_budget=prefs["loss_budget_usd"],
            sector_value=funds["sector_value"],
            existing_value=funds["existing_value"],
        )
        if quantity > risk["quantity"] or risk.get("risk_reward", 0) < 1.1:
            raise OrderRejected("수량·비중·손실 예산 또는 비용 차감 손익비를 초과했습니다.")
        reserved = limit * quantity + fee(limit, quantity)
        context = {
            "candidate": c,
            "research_id": research.id,
            "entry_fx": q["quality"]["fx_usdkrw"],
            "holding_days": prefs["holding_days"],
            "risk_at_limit": risk,
            "model": "클릭 이후 첫 합성 매도호가 + 5bp 슬리피지, 호가 잔량 최대 3주/틱, 지정가 상한",
        }
    else:
        pending_sell = db.scalar(
            select(func.coalesce(func.sum(Order.quantity - Order.filled), 0)).where(
                Order.instrument_id == item_id, Order.side == "sell", Order.status.in_(OPEN_ORDERS)
            )
        )
        if not pos or quantity > pos.quantity - pending_sell:
            raise OrderRejected("매도 가능 보유 수량을 초과했습니다.")
        reserved = D(0)
        context = {"model": "클릭 이후 첫 합성 매수호가 - 5bp 슬리피지, 호가 잔량 최대 3주/틱"}
    order = Order(
        idempotency_key=key,
        request_hash=digest,
        instrument_id=item_id,
        side=side,
        quantity=quantity,
        limit_price=limit,
        displayed_price=display,
        reserved=reserved,
        expires_at=now + timedelta(minutes=15),
        context=context,
        status="accepted",
    )
    db.add(order)
    db.flush()
    account.version += 1
    emit(db, "order:" + order.id, "order", {"order_id": order.id, "status": "accepted"})
    return order


def cancel(db, order_id):
    account = lock_account(db)
    order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if order is None:
        raise OrderRejected("주문을 찾을 수 없습니다.")
    if order.status in {"accepted", "pending", "partially_filled"}:
        order.status, order.reserved, order.updated_at = "cancelled", D(0), utcnow()
        account.version += 1
        emit(db, "cancel:" + order.id, "order", {"order_id": order.id, "status": order.status})
    return order


def apply_fill(db, order, fill_id, quantity, price, now):
    """Caller holds account/order locks; duplicate execution IDs are harmless."""
    if db.get(Fill, fill_id):
        return False
    if order.status not in {"accepted", "pending", "partially_filled"}:
        return False
    if quantity <= 0 or quantity > order.quantity - order.filled:
        raise OrderRejected("잘못된 체결 수량")
    account = db.get(Account, 1)
    pos = db.get(Position, order.instrument_id)
    price = D(price)
    costs = fee(price, quantity, order.side)
    db.add(Fill(id=fill_id, order_id=order.id, quantity=quantity, price=price, fee=costs, at=now))
    if order.side == "buy":
        candidate = order.context["candidate"]
        if not pos or pos.quantity == 0:
            if not pos:
                pos = Position(instrument_id=order.instrument_id)
                db.add(pos)
            pos.quantity, pos.average_price, pos.entry_fees = 0, D(0), D(0)
            pos.entry_fx = D(order.context["entry_fx"])
            pos.opened_at = now
            pos.version = 0
            end = holding_end(demo_clock(now), order.context["holding_days"])
            pos.original = {
                "candidate": candidate,
                "research_id": order.context["research_id"],
                "order_id": order.id,
                "target": candidate["target"],
                "stop": candidate["stop"],
                "holding_end": end.isoformat(),
                "simulation_entry_time": demo_clock(now).isoformat(),
                "strategy_version": candidate["strategy_version"],
                "changes": [],
            }
        pos.average_price = (pos.average_price * pos.quantity + price * quantity) / (pos.quantity + quantity)
        pos.quantity += quantity
        pos.entry_fees += costs
        pos.version += 1
        account.cash -= price * quantity + costs
        order.reserved = order.limit_price * (order.quantity - order.filled - quantity) + fee(
            order.limit_price, order.quantity - order.filled - quantity
        )
        original = dict(pos.original)
        original["risk_at_fill"] = size_position(
            entry=pos.average_price,
            stop=candidate["stop"],
            target=candidate["target"],
            cash=1000000,
            equity=1000000,
            budget=1000000,
            max_weight=1,
            loss_budget=1000000,
        )
        original["risk_at_fill"]["quantity"] = pos.quantity
        # Totals must reflect held shares, not the sizing routine's hypothetical maximum.
        risk_one = size_position(
            entry=pos.average_price,
            stop=candidate["stop"],
            target=candidate["target"],
            cash=pos.average_price + fee(pos.average_price, 1) + pos.average_price * SLIPPAGE_BPS / 10000,
            equity=1000000,
            budget=1000000,
            max_weight=1,
            loss_budget=1000000,
        )
        original["risk_at_fill"]["planned_loss"] = risk_one.get("planned_loss", 0) * pos.quantity
        original["risk_at_fill"]["stress_loss"] = risk_one.get("stress_loss", 0) * pos.quantity
        pos.original = original
    else:
        if not pos or pos.quantity < quantity:
            raise OrderRejected("보유 수량 대사 필요")
        allocated = pos.entry_fees * D(quantity) / pos.quantity
        account.realized += (price - pos.average_price) * quantity - costs - allocated
        account.cash += price * quantity - costs
        pos.quantity -= quantity
        pos.entry_fees -= allocated
        pos.version += 1
    order.average_price = (order.average_price * order.filled + price * quantity) / (order.filled + quantity)
    order.filled += quantity
    order.fees += costs
    order.status = "filled" if order.filled == order.quantity else "partially_filled"
    order.updated_at = now
    account.version += 1
    emit(
        db,
        "fill:" + fill_id,
        "fill",
        {"order_id": order.id, "quantity": quantity, "price": float(price), "status": order.status},
    )
    return True


def process_paper_orders(db):
    lock_account(db)
    now = utcnow()
    for order in db.scalars(
        select(Order)
        .where(Order.status.in_(["accepted", "pending", "partially_filled"]))
        .order_by(Order.created_at)
        .with_for_update()
    ):
        if order.mode != "demo-paper" or settings().data_mode != "demo":
            continue
        if order.expires_at <= now:
            order.status, order.reserved, order.updated_at = "cancelled", D(0), now
            continue
        q = quote_dict(db.get(Quote, order.instrument_id))
        valid, _ = quote_usable(q, now)
        if (
            not valid
            or q["source"] != "synthetic-v1"
            or datetime.fromisoformat(q["observed_at"]) <= order.created_at
        ):
            continue
        simulation_time = datetime.fromisoformat(q["quality"]["simulation_time"])
        if session_info(simulation_time)["state"] != "regular":
            continue
        if order.side == "buy":
            c = order.context["candidate"]
            if (
                any(
                    q["quality"].get(f) is not True
                    for f in ["warning_clear", "corporate_actions_clear", "events_clear"]
                )
                or q["last"] <= c["stop"]
                or q["last"] < c["indicators"]["ma20"]
            ):
                order.status, order.reserved, order.updated_at = "rejected", D(0), now
                emit(
                    db,
                    "invalidated:" + order.id,
                    "order",
                    {
                        "order_id": order.id,
                        "status": "rejected",
                        "message": "진입 대기 중 위험 또는 추세 조건 무효화",
                    },
                )
                continue
        raw = D(q["ask"] if order.side == "buy" else q["bid"])
        execution = cents(raw * (1 + SLIPPAGE_BPS / 10000 * (1 if order.side == "buy" else -1)))
        allowed = execution <= order.limit_price if order.side == "buy" else execution >= order.limit_price
        if not allowed:
            order.status = "pending" if not order.filled else "partially_filled"
            continue
        size = min(
            order.quantity - order.filled, q["quality"]["ask_size" if order.side == "buy" else "bid_size"]
        )
        apply_fill(db, order, f"paper:{order.id}:{q['sequence']}", size, execution, now)


def mark_submission_timeout(db, order_id):
    """Recovery primitive for a future broker: NEVER re-enqueue an unknown submission."""
    lock_account(db)
    order = db.get(Order, order_id)
    order.status = "needs_review"
    order.context = {**order.context, "reconciliation_required": True, "retry_submission": False}
