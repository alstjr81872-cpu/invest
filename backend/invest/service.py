"""Research snapshots and portfolio read models shared by the web and worker."""

from datetime import timedelta

import pandas as pd
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert

from .config import settings
from .db import utcnow
from .models import (
    Account,
    Instrument,
    Dataset,
    Quote,
    Recommendation,
    Position,
    Order,
    Event,
    Job,
    WorkerState,
)
from .providers import demo
from .providers.base import quote_usable
from .calendar import session_info, demo_clock, completed_sessions
from .analysis.selection import evaluate, market_summary
from .analysis.risk import value_position

OPEN_ORDERS = ["accepted", "pending", "partially_filled", "needs_review"]
DEFAULT_PREFERENCES = {
    "holding_days": 7,
    "target_pct": 1.0,
    "budget": 2500.0,
    "currency": "USD",
    "loss_budget_usd": 100.0,
    "max_weight": 0.25,
    "max_positions": 5,
    "existing_holdings": [],
}


def emit(db, key, kind, payload):
    db.execute(
        insert(Event)
        .values(key=key, kind=kind, payload=payload)
        .on_conflict_do_nothing(index_elements=["key"])
    )


def bootstrap(db):
    db.execute(
        insert(Account)
        .values(
            id=1,
            cash=10000,
            initial_cash=10000,
            realized=0,
            settings=DEFAULT_PREFERENCES,
            version=0,
            data_mode=settings().data_mode,
        )
        .on_conflict_do_nothing()
    )
    if db.get(Account, 1).data_mode != settings().data_mode:
        raise RuntimeError("DATA_MODE cannot be changed on an existing database; use a separate database")
    for identifier, ticker, exchange, name, sector, reference in demo.UNIVERSE + demo.BENCHMARKS:
        db.execute(
            insert(Instrument)
            .values(
                id=identifier,
                ticker=ticker,
                exchange=exchange,
                name=name,
                sector=sector,
                currency="USD",
                kind="index" if identifier.startswith("demo:") else "common_stock",
                aliases=[name, ticker],
            )
            .on_conflict_do_nothing()
        )
        if settings().data_mode == "demo":
            dataset = db.get(Dataset, identifier)
            expected = str(completed_sessions(demo_clock(utcnow()), 1)[-1].date())
            if dataset is None or not dataset.bars or dataset.bars[-1]["session"] != expected:
                bars = demo.history(identifier, reference, utcnow())
                metadata = {
                    "source": "synthetic-v1",
                    "demo": True,
                    "adjusted": True,
                    "generated_at": utcnow().isoformat(),
                    "actual_market_history": False,
                }
                if dataset is None:
                    db.add(Dataset(instrument_id=identifier, bars=bars, metadata_=metadata))
                else:
                    dataset.bars, dataset.metadata_ = bars, metadata


def instrument_dict(item: Instrument):
    return {
        "id": item.id,
        "ticker": item.ticker,
        "exchange": item.exchange,
        "name": item.name,
        "sector": item.sector,
        "currency": item.currency,
    }


def quote_dict(q: Quote | None):
    if q is None:
        return None
    return {
        "last": float(q.last),
        "bid": float(q.bid) if q.bid is not None else None,
        "ask": float(q.ask) if q.ask is not None else None,
        "observed_at": q.observed_at.isoformat(),
        "collected_at": q.collected_at.isoformat(),
        "available_at": q.available_at.isoformat(),
        "sequence": q.sequence,
        "source": q.source,
        "quality": q.quality,
    }


def ingest_quote(db, instrument_id, data):
    # Strictly monotonic event time AND sequence. An old reconnect event cannot rewind prices.
    statement = insert(Quote).values(instrument_id=instrument_id, **data)
    q = statement.excluded
    db.execute(
        statement.on_conflict_do_update(
            index_elements=[Quote.instrument_id],
            set_={k: getattr(q, k) for k in data},
            where=(Quote.sequence < q.sequence) & (Quote.observed_at <= q.observed_at),
        )
    )


def preferences(db):
    saved = {**DEFAULT_PREFERENCES, **db.get(Account, 1).settings}
    fx = 1350 if settings().data_mode == "demo" else None
    saved["budget_usd"] = saved["budget"] if saved["currency"] == "USD" else saved["budget"] / fx if fx else 0
    return saved


def exposure(db, item_id, pf, prefs):
    """Manual external holdings count toward concentration, never toward paper cash."""
    sector = db.get(Instrument, item_id).sector
    external_total, external_existing, external_sector = 0.0, 0.0, 0.0
    external_ids, missing = set(), False
    for holding in prefs.get("existing_holdings", []):
        identifier = holding["instrument_id"]
        external_ids.add(identifier)
        q = quote_dict(db.get(Quote, identifier))
        valid, _ = quote_usable(q, utcnow())
        if not valid:
            missing = True
            continue
        value = q["last"] * holding["quantity"]
        external_total += value
        if identifier == item_id:
            external_existing += value
        if db.get(Instrument, identifier).sector == sector:
            external_sector += value
    pending = list(db.scalars(select(Order).where(Order.side == "buy", Order.status.in_(OPEN_ORDERS))))
    existing = sum(
        p["valuation"]["market_value_usd"] for p in pf["positions"] if p["id"] == item_id and p["valuation"]
    )
    sector_value = sum(
        p["valuation"]["market_value_usd"]
        for p in pf["positions"]
        if p["sector"] == sector and p["valuation"]
    )
    sector_value += sum(
        float(o.reserved) for o in pending if db.get(Instrument, o.instrument_id).sector == sector
    )
    return {
        "cash": pf["available_cash"],
        "equity": pf["equity"] + external_total,
        "existing_value": existing + external_existing,
        "sector_value": sector_value + external_sector,
        "count": len({p["id"] for p in pf["positions"]} | external_ids | {o.instrument_id for o in pending}),
        "missing": missing,
    }


def portfolio(db):
    account = db.get(Account, 1)
    reserved = db.scalar(
        select(func.coalesce(func.sum(Order.reserved), 0)).where(Order.status.in_(OPEN_ORDERS))
    )
    positions, total_market, pnl = [], 0.0, 0.0
    for pos in db.scalars(select(Position).where(Position.quantity > 0).order_by(Position.opened_at)):
        q = quote_dict(db.get(Quote, pos.instrument_id))
        valid, reason = quote_usable(q, utcnow())
        item = instrument_dict(db.get(Instrument, pos.instrument_id))
        valuation = None
        if q:
            fx = q["quality"].get("fx_usdkrw")
            valuation = value_position(
                pos.quantity,
                pos.average_price,
                q["last"],
                q["bid"],
                pos.entry_fees,
                pos.entry_fx,
                fx or pos.entry_fx,
            )
            if fx is None:
                valuation["pnl_krw"] = None
                valuation["fx_component_krw"] = None
                valuation["fx_kind"] = "현재 환율 미연결"
            total_market += valuation["market_value_usd"]
            pnl += valuation["pnl_usd"]
        positions.append(
            {
                **item,
                "quantity": pos.quantity,
                "average_price": float(pos.average_price),
                "entry_fees": float(pos.entry_fees),
                "opened_at": pos.opened_at.isoformat(),
                "version": pos.version,
                "original": pos.original,
                "quote": q,
                "usable": valid,
                "data_state": reason,
                "valuation": valuation,
            }
        )
    return {
        "cash": float(account.cash),
        "available_cash": float(account.cash - reserved),
        "reserved": float(reserved),
        "initial_cash": float(account.initial_cash),
        "equity": float(account.cash) + total_market,
        "unrealized_pnl": pnl,
        "realized_pnl": float(account.realized),
        "positions": positions,
        "mode": "demo-paper" if settings().data_mode == "demo" else "live-data",
        "valuation_complete": all(p["usable"] for p in positions),
        "version": account.version,
    }


def create_research(db):
    prefs, pf = preferences(db), portfolio(db)
    market_ds = db.get(Dataset, "demo:sp500") if settings().data_mode == "demo" else None
    market_bars = market_ds.bars if market_ds else []
    market = market_summary(
        pd.DataFrame(market_bars) if market_bars else None,
        "S&P 500 형태 합성 지수 · 실제 지수 아님" if market_bars else "시장 지수 미연결",
    )
    candidates, inputs = [], {}
    expected_session = str(
        completed_sessions(demo_clock(utcnow()) if settings().data_mode == "demo" else utcnow(), 1)[-1].date()
    )
    all_items = db.scalars(
        select(Instrument).where(Instrument.kind == "common_stock").order_by(Instrument.ticker)
    )
    for item in all_items:
        q = quote_dict(db.get(Quote, item.id))
        ds = db.get(Dataset, item.id)
        sector_ds = db.get(Dataset, "demo:" + item.sector) if settings().data_mode == "demo" else None
        bars = ds.bars if ds and (settings().data_mode == "demo" or not ds.metadata_.get("demo")) else []
        valid, _ = quote_usable(q, utcnow())
        quality = {**(q["quality"] if q else {}), "quote_usable": valid and pf["valuation_complete"]}
        quality["daily_usable"] = bool(bars and bars[-1]["session"] == expected_session)
        inputs[item.id] = {
            "bars": bars,
            "quote": q,
            "quality": quality,
            "instrument": instrument_dict(item),
            "sector_bars": sector_ds.bars if sector_ds else [],
        }
        funds = exposure(db, item.id, pf, prefs)
        if funds["missing"]:
            quality["quote_usable"] = False
        candidate = evaluate(
            instrument_dict(item),
            bars,
            market_bars,
            sector_ds.bars if sector_ds else [],
            q or {},
            prefs,
            funds,
            quality,
        )
        if funds["count"] >= prefs["max_positions"] or funds["existing_value"]:
            candidate["status"] = " 매수 보류".strip()
            candidate["risks"].insert(0, "최대 보유 수 도달 또는 기존 보유 종목 · 추가 매수 미지원")
        candidates.append(candidate)
    candidates.sort(key=lambda c: c["score"] or -1, reverse=True)
    now = utcnow()
    payload = {
        "created_at": now.isoformat(),
        "settings": prefs,
        "strategy_version": "hypothesis-v1",
        "mode": settings().data_mode,
        "market": market,
        "candidates": candidates,
        "shortlist": [c["id"] for c in candidates if c["status"] == "조건 충족 시 진입 검토"][:5],
        "probability": "산출하지 않음",
        "news_state": "실제 뉴스 미연결 · 제목/본문 분석 미실행",
        "disclosures_state": "SEC 연결 검증 대기",
        "minute_bars": "미확보 · 1일 이내 전략 미지원",
        "input_snapshot": {
            "instruments": inputs,
            "market_bars": market_bars,
            "funds": pf,
            "expected_session": expected_session,
        },
    }
    rec = Recommendation(expires_at=now + timedelta(minutes=15), payload=payload)
    db.add(rec)
    db.flush()
    emit(
        db,
        "research:" + rec.id,
        "research",
        {"research_id": rec.id, "shortlist_count": len(payload["shortlist"])},
    )
    return {
        "id": rec.id,
        "expires_at": rec.expires_at.isoformat(),
        **{k: v for k, v in payload.items() if k != "input_snapshot"},
    }


def order_dict(order):
    return {
        "id": order.id,
        "instrument_id": order.instrument_id,
        "side": order.side,
        "status": order.status,
        "quantity": order.quantity,
        "filled": order.filled,
        "average_price": float(order.average_price),
        "displayed_price": float(order.displayed_price),
        "limit_price": float(order.limit_price),
        "fees": float(order.fees),
        "created_at": order.created_at.isoformat(),
        "mode": order.mode,
        "updated_at": order.updated_at.isoformat(),
        "context": order.context,
    }


def system_status(db):
    worker = db.get(WorkerState, 1)
    now = utcnow()
    worker_age = (now - worker.heartbeat).total_seconds() if worker else None
    result = {
        "server_time": now.isoformat(),
        "market": session_info(now),
        "demo_market": session_info(demo_clock(now)) if settings().data_mode == "demo" else None,
        "mode": settings().data_mode,
        "worker": {
            "connected": worker_age is not None and worker_age < 30,
            "heartbeat": worker.heartbeat.isoformat() if worker else None,
            "age_seconds": worker_age,
            "detail": worker.status if worker else {},
        },
        "poll_seconds": settings().worker_interval,
        "live_orders": {
            "enabled": False,
            "configured": settings().live_orders,
            "reason": "계좌·호가 권한·거래정지·대사와 실주문 통합 검증 미완료",
        },
        "providers": [
            {"name": "데모", "state": "합성 데이터" if settings().data_mode == "demo" else "비활성"},
            {"name": "한국투자증권", "state": "읽기 어댑터 준비 · 키/권한 검증 필요"},
            {"name": "SEC EDGAR", "state": "미연결 · 직접 문서/권한 검증 대기"},
            {"name": "뉴스·실적·경제일정·USD/KRW", "state": "실제 공급자 미연결"},
        ],
        "limitations": [
            "실제 시장 경보·거래정지·기업행동·과거 구성종목 미연결",
            "실제 주문 및 실제 시세 기반 모의 체결 비활성",
            "과거 전략 수익 검증 미완료",
        ],
    }
    if settings().free_tier:
        from .free_tier import usage

        result["free_tier"] = usage(db)
        result["poll_seconds"] = None
        result["limitations"] += [
            "수동 갱신만 수행 · 창을 닫으면 수집/체결/경보 없음",
            "무료 한도 소진 시 새 요청 중단 · 실제 공급자 사용량은 계정에서 확인",
        ]
    return result


def enqueue_analysis(db, instrument_id=None):
    pf = portfolio(db)
    selected = [p for p in pf["positions"] if instrument_id is None or p["id"] == instrument_id]
    if not selected:
        raise ValueError("분석할 보유 종목이 없습니다.")
    jobs = []
    for p in selected:
        stamp = int(utcnow().timestamp()) // 30
        key = f"analysis:{p['id']}:{p['version']}:{stamp}"
        db.execute(
            insert(Job)
            .values(
                id=__import__("uuid").uuid4().hex,
                dedup_key=key,
                kind="analysis",
                state="queued",
                payload={
                    "instrument_id": p["id"],
                    "position_version": p["version"],
                    "requested_at": utcnow().isoformat(),
                    "price": p["quote"]["last"] if p["quote"] else None,
                },
                attempts=0,
            )
            .on_conflict_do_nothing(index_elements=[Job.dedup_key])
        )
        job = db.scalar(select(Job).where(Job.dedup_key == key))
        jobs.append(job.id)
    return jobs
