from datetime import datetime, timedelta
import pandas as pd
from sqlalchemy import select

from ..db import utcnow
from ..config import settings
from ..models import Position, Quote, Dataset, Instrument, Job
from ..service import quote_dict, emit
from ..providers.base import quote_usable
from ..calendar import demo_clock, completed_sessions
from .indicators import indicators, validate_bars
from .selection import market_summary


def analyze_position(db, job):
    now = utcnow()
    payload = job.payload
    pos = db.get(Position, payload["instrument_id"])
    q = quote_dict(db.get(Quote, payload["instrument_id"]))
    ds = db.get(Dataset, payload["instrument_id"])
    valid, state = quote_usable(q, now)
    expected = str(
        completed_sessions(demo_clock(now) if settings().data_mode == "demo" else now, 1)[-1].date()
    )
    if q and any(
        q["quality"].get(field) is not True
        for field in ["warning_clear", "corporate_actions_clear", "events_clear"]
    ):
        valid, state = False, "필수 위험 상태 이상 또는 미확인"
    result = {
        "instrument_id": payload["instrument_id"],
        "requested_at": payload["requested_at"],
        "as_of": now.isoformat(),
        "valid_until": (now + timedelta(seconds=30)).isoformat(),
        "action": "데이터 부족",
        "changes": [],
        "reasons": [],
        "risks": [],
        "stale": not pos or pos.quantity <= 0 or pos.version != payload["position_version"],
        "position_version": payload["position_version"],
        "snapshot": {},
        "executed_order": False,
        "news": "미연결 · 종합 분석 미실행",
        "disclosures": "미연결",
        "minute_bars": "미확보",
    }
    if not pos or not pos.quantity:
        return {**result, "risks": ["분석 요청 이후 보유 수량 변경 또는 청산됨"]}
    if not valid or not ds or validate_bars(pd.DataFrame(ds.bars)) or ds.bars[-1]["session"] != expected:
        return {**result, "risks": ["최신 시세 또는 일봉 부족: " + state]}
    row = indicators(pd.DataFrame(ds.bars)).iloc[-1]
    market_ds = db.get(Dataset, "demo:sp500") if settings().data_mode == "demo" else None
    sector = db.get(Instrument, pos.instrument_id).sector
    sector_ds = db.get(Dataset, "demo:" + sector) if settings().data_mode == "demo" else None
    previous = db.scalar(
        select(Job)
        .where(
            Job.kind == "analysis",
            Job.state == "completed",
            Job.id != job.id,
            Job.payload["instrument_id"].astext == pos.instrument_id,
        )
        .order_by(Job.completed_at.desc())
        .limit(1)
    )
    previous_result = previous.result if previous else None
    price = q["last"]
    original = pos.original
    initial = original["candidate"].get("price", float(pos.average_price))
    result["changes"] = [
        f"최초 추천 가격 ${initial:.2f} → 현재 ${price:.2f}",
        f"20일 평균 ${row.ma20:.2f}, RSI {row.rsi:.1f}, ATR ${row.atr:.2f}로 일봉 재계산",
    ]
    if previous_result and previous_result.get("snapshot", {}).get("last"):
        old_price = previous_result["snapshot"]["last"]
        result["changes"].append(f"직전 분석 ${old_price:.2f} 대비 {(price / old_price - 1) * 100:+.2f}%")
    clock = demo_clock(now) if settings().data_mode == "demo" else now
    action = "보유 유지 검토"
    reason = "최초 목표/손절과 일봉 추세 조건이 유지됩니다."
    if clock >= datetime.fromisoformat(original["holding_end"]):
        action, reason = "전량 매도 검토", "최초 보유 만료에 도달했습니다. 자동 연장하지 않습니다."
    elif price <= original["stop"]:
        action, reason = "전량 매도 검토", "최초 손절 기준을 하회했습니다. 보호 주문이 접수된 것은 아닙니다."
    elif price >= original["target"]:
        action, reason = "일부 매도 검토", "최초 목표가에 도달했습니다. 매도는 별도 사용자 동작입니다."
    elif price < row.ma20:
        action, reason = "추가 관찰", "20일 이동평균 아래로 내려와 초기 추세 근거가 약해졌습니다."
    result.update(
        action=action,
        reasons=[reason, f"완성 일봉 기준일 {row.session}", "시장·업종의 완성 일봉을 함께 재계산했습니다."],
        risks=[
            "실제 뉴스·공시·분봉이 없어 해당 정보의 변화는 판단하지 않았습니다.",
            "합성 데이터 시연 · 실제 매매 판단으로 사용할 수 없습니다.",
            "갭·유동성 위험으로 경고 가격 체결은 보장되지 않습니다.",
        ],
        snapshot={
            "last": price,
            "quote": q,
            "daily_session": row.session,
            "indicators": {k: float(row[k]) for k in ["ma5", "ma20", "ma60", "rsi", "atr", "return5"]},
            "market": market_summary(pd.DataFrame(market_ds.bars) if market_ds else None, "합성 시장 기준"),
            "sector": market_summary(pd.DataFrame(sector_ds.bars) if sector_ds else None, "합성 업종 기준"),
        },
        original_levels={
            "stop": original["stop"],
            "target": original["target"],
            "holding_end": original["holding_end"],
        },
        proposed_changes=None,
        conditions="새 사건·시세 부실·포지션 변경 시 결과 무효. 주문은 별도로 제출하세요.",
    )
    if payload.get("price") and abs(price / payload["price"] - 1) > 0.01:
        result["stale"] = True
    return result


def automatic_alerts(db):
    for pos in db.scalars(select(Position).where(Position.quantity > 0)):
        q = quote_dict(db.get(Quote, pos.instrument_id))
        valid, state = quote_usable(q, utcnow())
        tag = (
            "data"
            if not valid
            else "stop"
            if q["last"] <= pos.original["stop"] * 1.01
            else "target"
            if (q["last"] >= pos.original["target"] * 0.99)
            else None
        )
        if tag:
            key = f"alert:{pos.instrument_id}:{tag}:{int(utcnow().timestamp()) // 3600}"
            emit(
                db,
                key,
                "alert",
                {
                    "instrument_id": pos.instrument_id,
                    "condition": tag,
                    "message": {
                        "data": "데이터 부족: " + state,
                        "stop": "최초 손절 기준 접근 · 보호 주문 아님",
                        "target": "최초 목표가 접근 · 매도는 사용자 동작",
                    }[tag],
                },
            )
