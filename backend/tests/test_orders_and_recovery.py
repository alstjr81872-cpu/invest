from datetime import timedelta
import uuid
from sqlalchemy import select, func

from invest.db import transaction, utcnow
from invest.models import Order, Position, Quote, Fill, Job
from invest.service import ingest_quote
from invest.providers.demo import quote
from invest.orders import process_paper_orders, apply_fill, lock_account, mark_submission_timeout
from invest.worker import process_one_job, claim_job


def send(owner, body, key=None):
    return owner.post("/api/orders", json=body, headers={"Idempotency-Key": key or str(uuid.uuid4())})


def next_tick(id, reference):
    with transaction() as db:
        ingest_quote(db, id, quote(id, reference, utcnow()))
        process_paper_orders(db)


def test_double_click_same_key_and_changed_payload(owner, buy_request):
    key = str(uuid.uuid4())
    a = send(owner, buy_request, key)
    b = send(owner, buy_request, key)
    assert a.status_code == b.status_code == 200, (a.text, b.text)
    assert a.json()["id"] == b.json()["id"]
    c = send(owner, {**buy_request, "quantity": 1}, key)
    assert c.status_code == 409
    with transaction() as db:
        assert db.scalar(select(func.count()).select_from(Order)) == 1


def test_no_fill_at_click_partial_fill_dedup_cancel_race_and_sell(owner, buy_request):
    r = send(owner, buy_request)
    assert r.status_code == 200, r.text
    o = r.json()
    id = buy_request["instrument_id"]
    assert o["filled"] == 0 and not owner.get("/api/portfolio").json()["positions"]
    with transaction() as db:
        process_paper_orders(db)
    assert owner.get("/api/orders").json()[0]["filled"] == 0
    next_tick(id, buy_request["displayed_price"])
    pos = owner.get("/api/portfolio").json()["positions"][0]
    assert pos["quantity"] == 3
    order = owner.get("/api/orders").json()[0]
    assert order["status"] == "partially_filled"
    with transaction() as db:
        lock_account(db)
        o = db.get(Order, order["id"])
        fills = list(db.scalars(select(Fill)))
        assert not apply_fill(db, o, fills[0].id, 1, 100, utcnow())
    # Cancellation wins the account lock; a later quote must not fill cancelled remainder.
    assert owner.post("/api/orders/" + order["id"] + "/cancel").status_code == 200
    next_tick(id, buy_request["displayed_price"])
    assert owner.get("/api/portfolio").json()["positions"][0]["quantity"] == 3
    sell = {
        **buy_request,
        "side": "sell",
        "quantity": 3,
        "limit_price": round(buy_request["displayed_price"] * 0.995, 2),
        "research_id": None,
    }
    response = send(owner, sell)
    assert response.status_code == 200, response.text
    next_tick(id, buy_request["displayed_price"])
    pf = owner.get("/api/portfolio").json()
    assert not pf["positions"]
    assert pf["realized_pnl"] < 0
    assert pf["reserved"] == 0


def test_full_fill_survives_new_client_and_weighted_average(owner, buy_request):
    result = send(owner, buy_request)
    assert result.status_code == 200, result.text
    next_tick(buy_request["instrument_id"], buy_request["displayed_price"])
    next_tick(buy_request["instrument_id"], buy_request["displayed_price"] * 1.0001)
    order = owner.get("/api/orders").json()[0]
    assert order["filled"] == buy_request["quantity"] and order["status"] == "filled"
    with transaction() as db:
        pos = db.get(Position, buy_request["instrument_id"])
        fills = list(db.scalars(select(Fill)))
        expected = sum(float(f.price) * f.quantity for f in fills) / pos.quantity
        assert abs(float(pos.average_price) - expected) < 0.00001
        assert pos.original["stop"] < float(pos.average_price) < pos.original["target"]
        assert pos.original["risk_at_fill"]["quantity"] == pos.quantity
    from fastapi.testclient import TestClient
    from invest.api import app

    with TestClient(app, base_url="https://testserver", headers={"Origin": "https://testserver"}) as fresh:
        login = fresh.post("/api/login", json={"username": "owner", "password": "test-password-only"})
        assert login.status_code == 200
        assert fresh.get("/api/portfolio").json()["positions"][0]["quantity"] == buy_request["quantity"]


def test_stale_and_delayed_block_orders(owner, buy_request):
    with transaction() as db:
        q = db.get(Quote, buy_request["instrument_id"])
        q.observed_at = utcnow() - timedelta(minutes=1)
    assert send(owner, buy_request).status_code == 409
    with transaction() as db:
        q = db.get(Quote, buy_request["instrument_id"])
        q.observed_at = utcnow()
        q.quality = {**q.quality, "delay_seconds": 900}
    assert send(owner, buy_request).status_code == 409


def test_real_order_default_is_disabled_even_when_flag_set(owner, buy_request, monkeypatch):
    from invest.config import settings

    monkeypatch.setenv("ENABLE_LIVE_ORDERS", "true")
    settings.cache_clear()
    try:
        assert send(owner, {**buy_request, "mode": "live-order"}).status_code == 409
    finally:
        settings.cache_clear()


def test_price_tolerance_and_changed_settings_block_order(owner, buy_request):
    assert send(owner, {**buy_request, "displayed_price": 1}).status_code == 409
    p = owner.get("/api/settings").json()
    p.pop("budget_usd")
    p["target_pct"] = 2
    owner.put("/api/settings", json=p)
    assert send(owner, buy_request).status_code == 409


def test_timeout_state_is_not_retried_or_cancelled(owner, buy_request):
    r = send(owner, buy_request)
    assert r.status_code == 200
    with transaction() as db:
        mark_submission_timeout(db, r.json()["id"])
    next_tick(buy_request["instrument_id"], buy_request["displayed_price"])
    assert owner.get("/api/orders").json()[0]["status"] == "needs_review"
    owner.post("/api/orders/" + r.json()["id"] + "/cancel")
    assert owner.get("/api/orders").json()[0]["status"] == "needs_review"


def test_expired_lease_recovers_analysis_without_order(owner, buy_request):
    assert send(owner, buy_request).status_code == 200
    next_tick(buy_request["instrument_id"], buy_request["displayed_price"])
    before = len(owner.get("/api/orders").json())
    ids = owner.post("/api/analysis", json={"instrument_id": buy_request["instrument_id"]}).json()["jobs"]
    with transaction() as db:
        j = claim_job(db)
        assert j.id == ids[0]
        j.lease_until = utcnow() - timedelta(seconds=1)
    assert process_one_job()
    j = owner.get("/api/jobs").json()[0]
    assert j["state"] == "completed" and j["result"]["snapshot"]["indicators"]
    assert len(owner.get("/api/orders").json()) == before
    with transaction() as db:
        pos = db.get(Position, buy_request["instrument_id"])
        pos.version += 1
    assert owner.get("/api/jobs").json()[0]["result"]["stale"]


def test_two_workers_cannot_claim_same_job():
    with transaction() as db:
        db.add(Job(dedup_key="a", kind="analysis", payload={}, state="queued"))
    with transaction() as first:
        job = claim_job(first)
        assert job
        with transaction() as second:
            assert claim_job(second) is None
