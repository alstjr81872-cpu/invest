from datetime import timedelta
import pytest
from starlette.websockets import WebSocketDisconnect

from invest.analysis.backtest import exit_for_bar, run_backtest, split_position
from invest.providers.demo import history
from invest.db import utcnow, transaction
from invest.models import AuthSession
from invest.auth import digest, COOKIE_NAME


def test_private_routes_and_websocket_reject_unauthenticated(client):
    for route in [
        "/api/portfolio",
        "/api/orders",
        "/api/settings",
        "/api/jobs",
        "/api/history",
        "/api/status",
    ]:
        assert client.get(route).status_code == 401
    assert client.get("/healthz").json() == {"status": "ok"}
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            "wss://testserver/api/stream", headers={"origin": "https://testserver"}
        ):
            pass


def test_csrf_origin_session_cookie_logout_and_websocket(owner):
    assert owner.get("/api/session").status_code == 200
    token = owner.cookies.get(COOKIE_NAME)
    assert token and len(token) > 32
    response = owner.post("/api/research", headers={"X-CSRF-Token": "bad"})
    assert response.status_code == 403
    assert owner.post("/api/research", headers={"Origin": "https://evil.test"}).status_code == 403
    with pytest.raises(WebSocketDisconnect):
        with owner.websocket_connect("wss://testserver/api/stream", headers={"origin": "https://evil.test"}):
            pass
    with owner.websocket_connect(
        "wss://testserver/api/stream", headers={"origin": "https://testserver"}
    ) as ws:
        assert ws.receive_json()["type"] == "snapshot"
    assert owner.post("/api/logout").status_code == 200
    assert owner.get("/api/portfolio").status_code == 401
    from invest.auth import authenticate

    assert authenticate(token) is None


def test_login_rate_limit_and_secure_cookie(client):
    for _ in range(5):
        assert client.post("/api/login", json={"username": "owner", "password": "wrong"}).status_code == 401
    assert (
        client.post("/api/login", json={"username": "owner", "password": "test-password-only"}).status_code
        == 429
    )


def test_login_cookie_attributes_and_session_expiry(client):
    r = client.post("/api/login", json={"username": "owner", "password": "test-password-only"})
    cookie = r.headers["set-cookie"].lower()
    assert "secure" in cookie and "httponly" in cookie and "samesite=strict" in cookie
    assert "max-age=28800" in cookie
    with transaction() as db:
        db.get(AuthSession, digest(client.cookies.get(COOKIE_NAME))).expires_at = utcnow() - timedelta(
            seconds=1
        )
    assert client.get("/api/session").status_code == 401


def test_gap_and_same_bar_ambiguity_and_halt():
    assert exit_for_bar({"open": 90, "low": 85, "high": 120}, 95, 110) == (90.0, "stop_gap")
    assert exit_for_bar({"open": 100, "low": 94, "high": 111}, 95, 110) == (95.0, "stop_first_conservative")
    assert exit_for_bar({"open": 115, "low": 112, "high": 116}, 95, 110) == (110.0, "target_gap_conservative")


def test_backtest_future_information_cost_expiry_and_time_partitions():
    bars = history("test:backtest", 100, utcnow(), 420)
    r = run_backtest(bars, 2)
    assert r["trades_count"] > 0
    assert all(t["signal_index"] < t["entry_index"] for t in r["trades"])
    assert all(t["signal_session"] < t["entry_session"] for t in r["trades"])
    assert all(t["entry_fee"] > 0 and t["exit_fee"] > 0 for t in r["trades"])
    assert r["expiry_count"] > 0
    assert r["splits"]["development"][1] + 2 <= r["splits"]["validation"][0]
    assert r["market_excess_return_pct"] is None
    # A delayed historical bar cannot create a signal at its close.
    delayed = [{**b, "available_at": "2099-01-01T00:00:00+00:00"} for b in bars]
    assert run_backtest(delayed, 2)["trades_count"] == 0
    halted = [{**b, "halted": True} for b in bars]
    assert run_backtest(halted, 2)["trades_count"] == 0


def test_split_preserves_value_and_fractional_requires_feed():
    qty, average = split_position(10, 100, 4)
    assert qty == 40 and average == 25 and qty * average == 1000
    with pytest.raises(ValueError):
        split_position(1, 100, 0.5)


def test_backtest_job_completed_by_worker(owner):
    from invest.worker import process_one_job

    r = owner.post("/api/backtest", json={"instrument_id": "cik:0000320193", "holding_days": 5})
    assert r.status_code == 200
    assert process_one_job()
    job = owner.get("/api/jobs").json()[0]
    assert job["state"] == "completed", job
    assert set(job["result"]["partition_results"]) == {"development", "validation", "final"}


def test_validation_errors_do_not_echo_passwords(client):
    secret = "do-not-echo-this-password-" * 30
    response = client.post("/api/login", json={"username": "owner", "password": secret})
    assert response.status_code == 422
    assert secret not in response.text and "do-not-echo" not in response.text


def test_failed_analysis_remains_an_observable_failure(owner):
    from invest.models import Job

    with transaction() as db:
        db.add(
            Job(
                dedup_key="failed-expected",
                kind="analysis",
                state="failed",
                payload={"instrument_id": "cik:0000320193"},
                result={"error": "필수 데이터 누락"},
            )
        )
    response = owner.get("/api/jobs")
    assert response.status_code == 200
    assert response.json()[0]["state"] == "failed"
    assert response.json()[0]["result"]["error"] == "필수 데이터 누락"
