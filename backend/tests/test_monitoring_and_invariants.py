from datetime import timedelta
import uuid

import pytest

from invest.db import transaction, utcnow
from invest.models import Position, Quote, Recommendation, Dataset, Account, WorkerState
from invest.service import bootstrap, ingest_quote
from invest.orders import process_paper_orders
from invest.providers.demo import quote
from invest.worker import process_one_job, tick
from invest.config import settings
from invest.analysis.news import historically_available


def make_position(owner, buy_request):
    r = owner.post("/api/orders", json=buy_request, headers={"Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    with transaction() as db:
        ingest_quote(
            db,
            buy_request["instrument_id"],
            quote(buy_request["instrument_id"], buy_request["displayed_price"], utcnow()),
        )
        process_paper_orders(db)
    return buy_request["instrument_id"]


def test_monitor_recomputes_expiry_without_loosening_stop_or_auto_selling(owner, buy_request):
    id = make_position(owner, buy_request)
    with transaction() as db:
        p = db.get(Position, id)
        original = dict(p.original)
        stop = original["stop"]
        target = original["target"]
        original["holding_end"] = "2020-01-01T20:00:00+00:00"
        p.original = original
    count = len(owner.get("/api/orders").json())
    assert owner.post("/api/analysis", json={"instrument_id": id}).status_code == 200
    assert process_one_job()
    result = owner.get("/api/jobs").json()[0]["result"]
    assert result["action"] == "전량 매도 검토"
    assert result["original_levels"]["stop"] == stop and result["original_levels"]["target"] == target
    assert result["executed_order"] is False and result["proposed_changes"] is None
    assert result["snapshot"]["sector"]["facts"]
    assert len(owner.get("/api/orders").json()) == count


def test_analysis_late_price_and_stale_quote_are_not_normal(owner, buy_request):
    id = make_position(owner, buy_request)
    owner.post("/api/analysis", json={"instrument_id": id})
    assert process_one_job()
    with transaction() as db:
        q = db.get(Quote, id)
        q.last *= __import__("decimal").Decimal("1.05")
    assert owner.get("/api/jobs").json()[0]["result"]["stale"]
    with transaction() as db:
        q = db.get(Quote, id)
        q.observed_at = utcnow() - timedelta(minutes=2)
        p = db.get(Position, id)
        p.version += 1
    owner.post("/api/analysis", json={"instrument_id": id})
    assert process_one_job()
    result = owner.get("/api/jobs").json()[0]["result"]
    assert result["action"] == "데이터 부족"


def test_pending_buy_rechecks_risk_before_next_fill(owner, buy_request):
    r = owner.post("/api/orders", json=buy_request, headers={"Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    with transaction() as db:
        data = quote(buy_request["instrument_id"], buy_request["displayed_price"], utcnow())
        data["quality"]["events_clear"] = False
        ingest_quote(db, buy_request["instrument_id"], data)
        process_paper_orders(db)
    order = owner.get("/api/orders").json()[0]
    assert order["status"] == "rejected" and order["filled"] == 0
    assert owner.get("/api/portfolio").json()["reserved"] == 0


def test_research_saves_inputs_and_stale_daily_bars_fail_closed(owner, research):
    with transaction() as db:
        r = db.get(Recommendation, research["id"])
        snap = r.payload["input_snapshot"]
        assert snap["instruments"]["cik:0000320193"]["bars"]
        ds = db.get(Dataset, "cik:0000320193")
        ds.bars = ds.bars[:-1]
    result = owner.post("/api/research").json()
    c = next(c for c in result["candidates"] if c["id"] == "cik:0000320193")
    assert c["status"] == "데이터 부족"
    assert "input_snapshot" not in result


def test_mode_switch_cannot_mix_live_and_demo(monkeypatch):
    monkeypatch.setenv("DATA_MODE", "live-data")
    settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="separate database"):
            with transaction() as db:
                bootstrap(db)
    finally:
        settings.cache_clear()


def test_date_only_news_uses_next_session_and_bad_timestamps_are_excluded():
    from datetime import datetime

    item = {"available_at": "2026-07-02"}
    assert not historically_available(item, datetime.fromisoformat("2026-07-02T21:00:00+00:00"))
    assert historically_available(item, datetime.fromisoformat("2026-07-06T13:30:00+00:00"))
    assert not historically_available({"available_at": "2026-07-02T12:00:00"}, utcnow())
    assert not historically_available({"available_at": "bad"}, utcnow())


def test_worker_reconnection_records_gap_and_preserves_state():
    with transaction() as db:
        db.add(WorkerState(id=1, heartbeat=utcnow() - timedelta(seconds=90), status={}))
    tick(None)
    with transaction() as db:
        state = db.get(WorkerState, 1)
        assert state.status["gap_seconds"] > 80 and state.status["received"] == 6
        assert db.get(Account, 1).cash == 10000
