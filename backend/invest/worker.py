"""Standalone long-running collector and durable job executor; no browser dependency."""

import logging
import signal
import threading
from datetime import timedelta

from sqlalchemy import select, text, or_
from sqlalchemy.exc import SQLAlchemyError

from .config import settings
from .db import transaction, utcnow, engine
from .models import Instrument, Dataset, Job, WorkerState
from .service import bootstrap, ingest_quote, emit
from .providers import demo
from .providers.kis import KIS
from .providers.base import ProviderError
from .orders import process_paper_orders
from .analysis.monitor import analyze_position, automatic_alerts
from .analysis.backtest import run_backtest, time_splits

log = logging.getLogger("invest.worker")
stop = threading.Event()


def claim_job(db):
    now = utcnow()
    job = db.scalar(
        select(Job)
        .where(or_(Job.state == "queued", (Job.state == "running") & (Job.lease_until < now)))
        .order_by(Job.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job:
        job.state, job.lease_until, job.attempts = "running", now + timedelta(seconds=60), job.attempts + 1
    return job


def process_one_job():
    with transaction() as db:
        job = claim_job(db)
        if not job:
            return False
        job_id = job.id
        attempt = job.attempts
    # Calculation and result persistence hold the row lock. A process crash rolls back this
    # transaction; the separate claim lease makes recovery observable and bounded.
    with transaction(isolation="REPEATABLE READ") as db:
        job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if job.state != "running" or job.attempts != attempt:
            return False
        try:
            if job.kind == "analysis":
                result = analyze_position(db, job)
            elif job.kind == "backtest":
                if settings().data_mode != "demo":
                    raise ValueError("검증된 장기 실데이터가 없습니다.")
                ds = db.get(Dataset, job.payload["instrument_id"])
                if not ds or not ds.metadata_.get("demo"):
                    raise ValueError("합성 일봉이 없습니다.")
                days = job.payload["holding_days"]
                splits = time_splits(len(ds.bars), days)
                result = run_backtest(ds.bars, days, start=splits["final"][0], end=splits["final"][1])
                result["partition_results"] = {
                    part: {
                        k: v
                        for k, v in run_backtest(ds.bars, days, start=bounds[0], end=bounds[1]).items()
                        if k in {"period", "return_pct", "trades_count", "max_drawdown_pct"}
                    }
                    for part, bounds in splits.items()
                    if part in {"development", "validation", "final"}
                }
            else:
                raise ValueError("지원하지 않는 작업")
            job.result, job.state = result, "completed"
        except (ValueError, KeyError) as exc:
            job.state = "failed"
            job.result = {"error": str(exc) if isinstance(exc, ValueError) else "필수 데이터 누락"}
        job.completed_at, job.lease_until = utcnow(), None
        emit(
            db,
            "job:" + job.id,
            "analysis" if job.kind == "analysis" else "backtest",
            {"job_id": job.id, "state": job.state},
        )
    return True


def tick(kis, *, max_jobs=10):
    errors, received = [], 0
    with transaction() as db:
        bootstrap(db)
        items = [
            (i.id, i.ticker, i.exchange)
            for i in db.scalars(select(Instrument).where(Instrument.kind == "common_stock"))
        ]
    for identifier, ticker, exchange in items:
        try:
            with transaction() as db:
                if settings().data_mode == "demo":
                    ds = db.get(Dataset, identifier)
                    data = demo.quote(identifier, ds.bars[-1]["close"], utcnow())
                else:
                    data = kis.price(ticker, exchange)
                ingest_quote(db, identifier, data)
                received += 1
        except ProviderError as exc:
            errors.append({"ticker": ticker, "code": exc.code})
    with transaction() as db:
        if settings().data_mode == "demo":
            process_paper_orders(db)
        automatic_alerts(db)
        previous = db.get(WorkerState, 1)
        gap = (utcnow() - previous.heartbeat).total_seconds() if previous else None
        status = {
            "mode": settings().data_mode,
            "received": received,
            "errors": errors,
            "gap_seconds": gap if gap and gap > 30 else None,
            "live_reconciliation": "미연결",
            "poll_seconds": settings().worker_interval,
        }
        if previous:
            previous.heartbeat, previous.status = utcnow(), status
        else:
            db.add(WorkerState(id=1, heartbeat=utcnow(), status=status))
        if gap and gap > 30:
            emit(
                db,
                f"gap:{int(utcnow().timestamp())}",
                "alert",
                {"message": f"워커 수집 공백 {gap:.0f}초 · 새 시세로 복구"},
            )
    for _ in range(max_jobs):
        if not process_one_job():
            break


def main():
    if settings().free_tier:
        raise SystemExit("FREE_TIER_MODE: no background worker; use authenticated /api/refresh")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    kis = KIS()
    # Session-level advisory lock prevents two collectors from double-filling on rolling deploy.
    while not stop.is_set():
        try:
            with engine().connect() as leader:
                if not leader.scalar(text("SELECT pg_try_advisory_lock(71382061)")):
                    leader.rollback()
                    stop.wait(5)
                    continue
                leader.commit()
                log.info("collector leadership acquired; durable state restored")
                try:
                    while not stop.is_set():
                        # Detect lost DB session before touching account state.
                        leader.execute(text("SELECT 1"))
                        leader.commit()
                        tick(kis)
                        stop.wait(settings().worker_interval)
                finally:
                    leader.execute(text("SELECT pg_advisory_unlock(71382061)"))
                    leader.commit()
        except SQLAlchemyError:
            log.error("database connection interrupted; retrying without resubmitting external orders")
            stop.wait(5)
    log.info("worker stopped gracefully")


if __name__ == "__main__":
    main()
