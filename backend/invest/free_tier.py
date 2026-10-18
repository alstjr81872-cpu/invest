"""Conservative application budgets, not a substitute for provider billing limits.

All API calls share a durable monthly counter, including rejected login attempts.
Cached denials avoid repeatedly waking the DB after exhaustion in this process.
Only the provider's Free plan / no payment method prevents provider overage bills.
"""

from datetime import timedelta
from threading import Lock
from time import monotonic

from fastapi import HTTPException
from sqlalchemy import select, text, func, delete
from sqlalchemy.dialects.postgresql import insert

from .db import transaction, utcnow, engine
from .models import UsageBudget, Recommendation, Job, Order, Event, AuthSession

# Even if each request wakes a 2-CU compute for six minutes, 300 requests reserve
# ~60 CUh, below the documented 100 CUh. Restarts, other clients, failed probes,
# migrations, timeouts and provider meters are outside this estimate.
LIMITS = {
    "api": (80, 300),
    "refresh": (10, 60),
    "research": (5, 30),
    "analysis": (10, 60),
    "backtest": (2, 10),
    "order": (10, 60),
}
STORAGE_BYTES = 300_000_000
ROW_LIMITS = ((Recommendation, 200), (Job, 500), (Order, 1000), (Event, 10000))
_lock = Lock()
_blocked = {}
_recent = []


def category(path, method):
    if method not in {"POST", "PUT"}:
        return None
    return {
        "/api/refresh": "refresh",
        "/api/research": "research",
        "/api/analysis": "analysis",
        "/api/backtest": "backtest",
        "/api/orders": "order",
    }.get(path)


def reset_local_gate():
    """Only for isolated tests. Durable counters are never reset by this function."""
    with _lock:
        _blocked.clear()
        _recent.clear()


def _reject(until, message):
    return HTTPException(
        429, message, headers={"Retry-After": str(max(1, int((until - utcnow()).total_seconds())))}
    )


def reserve(path, method):
    now = utcnow()
    kind = category(path, method)
    keys = ["api"] + ([kind] if kind else [])
    with _lock:
        for key in keys:
            blocked = _blocked.get(key)
            if blocked and blocked[0] > now:
                raise _reject(*blocked)
        stamp = monotonic()
        _recent[:] = [v for v in _recent if stamp - v < 60]
        if len(_recent) >= 30:
            raise HTTPException(
                429, "요청이 많습니다. 1분 후 다시 시도하세요.", headers={"Retry-After": "60"}
            )
        _recent.append(stamp)
    day_end = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    month_end = (now.replace(day=28) + timedelta(days=4)).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    denial = None
    with transaction() as db:
        # Fixed acquisition order serializes limits across threads, replicas and restarts.
        rows = []
        for period, index, end in [
            (now.strftime("%Y-%m"), 1, month_end),
            (now.strftime("%Y-%m-%d"), 0, day_end),
        ]:
            db.execute(insert(UsageBudget).values(period=period, counters={}).on_conflict_do_nothing())
            row = db.scalar(select(UsageBudget).where(UsageBudget.period == period).with_for_update())
            rows.append(row)
            for key in keys:
                if row.counters.get(key, 0) >= LIMITS[key][index]:
                    denial = (
                        key,
                        end,
                        "무료 사용량 보호 한도에 도달했습니다. 한도가 초기화될 때까지 작업을 중단합니다.",
                    )
                    break
            if denial:
                break
        if not denial:
            for row in rows:
                row.counters = {**row.counters, **{key: row.counters.get(key, 0) + 1 for key in keys}}
    if denial:
        key, until, message = denial
        with _lock:
            _blocked[key] = (until, message)
        raise _reject(until, message)


def storage_guard():
    # Run before writes. Stop rather than silently deleting research or trading history.
    with transaction() as db:
        if db.scalar(text("SELECT pg_database_size(current_database())")) >= STORAGE_BYTES:
            raise HTTPException(
                507, "무료 DB 저장 보호 한도에 도달했습니다. 내보내기 후 보관 정책을 검토하세요."
            )
        for model, limit in ROW_LIMITS:
            if db.scalar(select(func.count()).select_from(model)) >= limit:
                raise HTTPException(
                    507, "무료 기록 보관 한도에 도달했습니다. 기존 기록은 삭제하지 않고 새 작업을 중단합니다."
                )
        # Expired/revoked authentication material is not investment history.
        db.execute(delete(AuthSession).where((AuthSession.expires_at <= utcnow()) | AuthSession.revoked))
        if db.scalar(select(func.count()).select_from(AuthSession)) >= 64:
            raise HTTPException(429, "활성 로그인 세션이 많습니다. 기존 세션을 로그아웃하세요.")


def usage(db):
    now = utcnow()
    result = {}
    for period, index, label in [
        (now.strftime("%Y-%m-%d"), 0, "daily"),
        (now.strftime("%Y-%m"), 1, "monthly"),
    ]:
        row = db.get(UsageBudget, period)
        result[label] = {
            k: {"used": (row.counters if row else {}).get(k, 0), "limit": v[index]} for k, v in LIMITS.items()
        }
    return {
        "enabled": True,
        "usage": result,
        "storage_limit_bytes": STORAGE_BYTES,
        "provider_meter": "앱 요청 예산 · 공급자의 실제 청구 계량 아님",
        "refresh": "manual",
    }


def refresh():
    from .worker import tick
    from .providers.kis import KIS

    # Same leadership key as the native collector. Never run competing quote/fill ticks.
    with engine().connect() as leader:
        if not leader.scalar(text("SELECT pg_try_advisory_lock(71382061)")):
            raise HTTPException(409, "이미 갱신 중입니다. 잠시 후 상태를 확인하세요.")
        leader.commit()
        try:
            tick(KIS(), max_jobs=0)
        finally:
            leader.execute(text("SELECT pg_advisory_unlock(71382061)"))
            leader.commit()


def complete_jobs(maximum):
    from .worker import process_one_job

    for _ in range(maximum):
        if not process_one_job():
            break
