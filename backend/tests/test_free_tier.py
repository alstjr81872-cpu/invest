from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select, func

from invest import free_tier
from invest.config import settings, validate_web_config
from invest.db import transaction, utcnow
from invest.models import UsageBudget, Order, Quote


@pytest.fixture
def free_mode(monkeypatch):
    monkeypatch.setenv("FREE_TIER_MODE", "true")
    settings.cache_clear()
    free_tier.reset_local_gate()
    yield
    settings.cache_clear()
    free_tier.reset_local_gate()


def test_no_database_health_or_anonymous_probe(free_mode, client, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("health/anonymous session must not wake Neon")

    monkeypatch.setattr(free_tier, "reserve", forbidden)
    assert client.get("/healthz").json()["database"] == "checked-on-owner-request"
    assert client.get("/api/session").status_code == 401
    assert client.post("/api/login", json={}, headers={"Origin": "https://evil.test"}).status_code == 403


def test_durable_limit_atomic_under_concurrency_and_restart(free_mode, monkeypatch):
    monkeypatch.setitem(free_tier.LIMITS, "api", (7, 7))

    def reserve(_):
        try:
            free_tier.reserve("/api/dashboard", "GET")
            return True
        except HTTPException as exc:
            assert exc.status_code == 429
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(reserve, range(20))) == 7
    free_tier.reset_local_gate()  # Simulate process restart, not a billing reset.
    assert not reserve(0)
    with transaction() as db:
        assert db.get(UsageBudget, utcnow().strftime("%Y-%m")).counters["api"] == 7


def test_cached_denial_does_not_repeatedly_query_database(free_mode, monkeypatch):
    monkeypatch.setitem(free_tier.LIMITS, "api", (1, 1))
    free_tier.reserve("/api/dashboard", "GET")
    with pytest.raises(HTTPException):
        free_tier.reserve("/api/dashboard", "GET")

    def forbidden():
        raise AssertionError("exhausted requests must be rejected before connecting")

    monkeypatch.setattr(free_tier, "transaction", forbidden)
    with pytest.raises(HTTPException) as exc:
        free_tier.reserve("/api/dashboard", "GET")
    assert exc.value.status_code == 429


def test_action_budget_leaves_read_access(free_mode, owner, monkeypatch):
    monkeypatch.setitem(free_tier.LIMITS, "research", (1, 1))
    assert owner.post("/api/research").status_code == 200
    response = owner.post("/api/research")
    assert response.status_code == 429 and int(response.headers["Retry-After"]) > 0
    assert owner.get("/api/dashboard").status_code == 200


def test_storage_guard_preserves_records(free_mode, owner, monkeypatch):
    monkeypatch.setattr(free_tier, "STORAGE_BYTES", 1)
    assert owner.post("/api/research").status_code == 507
    assert owner.get("/api/dashboard").status_code == 200
    with transaction() as db:
        assert db.scalar(select(func.count()).select_from(Order)) == 0


def test_manual_research_buy_partial_fill_analysis_backtest_and_sell(free_mode, owner):
    research = owner.post("/api/research").json()
    c = next(c for c in research["candidates"] if c["id"] in research["shortlist"])
    request = {
        "instrument_id": c["id"],
        "side": "buy",
        "mode": "demo-paper",
        "quantity": 5,
        "limit_price": round(c["price"] * 1.004, 2),
        "displayed_price": c["price"],
        "research_id": research["id"],
    }
    key = str(uuid4())
    order = owner.post("/api/orders", json=request, headers={"Idempotency-Key": key})
    assert order.status_code == 200, order.text
    assert order.json()["filled"] == 0
    duplicate = owner.post("/api/orders", json=request, headers={"Idempotency-Key": key})
    assert duplicate.json()["id"] == order.json()["id"]
    response = owner.post("/api/refresh")
    assert response.status_code == 200, response.text
    assert response.json()["portfolio"]["positions"][0]["quantity"] == 3
    result = owner.post("/api/refresh").json()
    assert result["portfolio"]["positions"][0]["quantity"] == 5
    assert result["status"]["free_tier"]["enabled"]
    assert owner.post("/api/analysis", json={"instrument_id": c["id"]}).status_code == 200
    assert owner.get("/api/jobs").json()[0]["state"] == "completed"
    assert owner.post("/api/backtest", json={"instrument_id": c["id"], "holding_days": 7}).status_code == 200
    assert owner.get("/api/jobs").json()[0]["state"] == "completed"
    with transaction() as db:
        q = db.get(Quote, c["id"])
        request.update(
            side="sell",
            research_id=None,
            displayed_price=float(q.last),
            limit_price=round(float(q.last) * 0.996, 2),
        )
    sell = owner.post("/api/orders", json=request, headers={"Idempotency-Key": str(uuid4())})
    assert sell.status_code == 200, sell.text
    assert owner.post("/api/refresh").status_code == 200
    result = owner.post("/api/refresh").json()
    assert not result["portfolio"]["positions"]
    assert result["events"]


def test_stale_quotes_still_reject_buys_in_manual_mode(free_mode, owner):
    r = owner.post("/api/research").json()
    c = next(c for c in r["candidates"] if c["id"] in r["shortlist"])
    with transaction() as db:
        db.get(Quote, c["id"]).observed_at = utcnow() - timedelta(minutes=10)
    response = owner.post(
        "/api/orders",
        json={
            "instrument_id": c["id"],
            "side": "buy",
            "mode": "demo-paper",
            "quantity": 1,
            "limit_price": c["price"],
            "displayed_price": c["price"],
            "research_id": r["id"],
        },
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 409


def test_free_mode_refuses_standalone_worker_and_live_orders(free_mode, monkeypatch):
    from invest.worker import main

    with pytest.raises(SystemExit, match="no background worker"):
        main()
    monkeypatch.setenv("ENABLE_LIVE_ORDERS", "true")
    settings.cache_clear()
    with pytest.raises(RuntimeError, match="paper orders only"):
        validate_web_config(settings())


def test_free_mode_disables_websockets(free_mode, owner):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with owner.websocket_connect("/api/stream"):
            pytest.fail("Free mode must not keep a DB stream open")


def test_free_deployment_checker_rejects_pooler_and_unverified_tls(free_mode):
    import importlib.util
    from dataclasses import replace

    spec = importlib.util.spec_from_file_location("free_check", "scripts/check_free_config.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    good = "postgresql+psycopg://u:p@ep-example.us-west-2.aws.neon.tech/db?sslmode=verify-full&sslrootcert=system&channel_binding=require"
    config = replace(settings(), database_url=good)
    module.validate(config)
    with pytest.raises(ValueError, match="direct"):
        module.validate(replace(config, database_url=good.replace("ep-example.", "ep-example-pooler.")))
    with pytest.raises(ValueError, match="verify-full"):
        module.validate(replace(config, database_url=good.replace("verify-full", "require")))
