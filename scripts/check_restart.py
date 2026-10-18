"""Acceptance test: kill web/worker during a partial fill, restart and replay the same key.

Uses only a dedicated PostgreSQL database ending _test. Never touches a broker API.
"""

import os
import secrets
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
from argon2 import PasswordHasher
from sqlalchemy.engine import make_url
from sqlalchemy import text, select, func
from invest.db import transaction, Base
from invest import models

root = Path(__file__).resolve().parent.parent
os.chdir(root)
url = os.getenv(
    "RESTART_DATABASE_URL",
    "postgresql+psycopg://invest:local-development-only@127.0.0.1:55432/invest_restart_test",
)
if not make_url(url).database.endswith("_test"):
    raise SystemExit("Refusing to clear a non-test database")
password = secrets.token_urlsafe(24)
os.environ.update(
    DATABASE_URL=url,
    APP_ORIGIN="http://127.0.0.1:8012",
    COOKIE_SECURE="false",
    OWNER_USERNAME="owner",
    OWNER_PASSWORD_HASH=PasswordHasher().hash(password),
    SESSION_SECRET=secrets.token_urlsafe(48),
    DATA_MODE="demo",
    ENABLE_LIVE_ORDERS="false",
    FREE_TIER_MODE="false",
    WORKER_INTERVAL_SECONDS="5",
)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)

with transaction() as db:
    db.execute(
        text(
            "TRUNCATE "
            + ", ".join('"' + t.name + '"' for t in Base.metadata.sorted_tables)
            + " RESTART IDENTITY CASCADE"
        )
    )
(root / ".local").mkdir(exist_ok=True)
children = []


def start(log):
    web = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "invest.api:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8012",
            "--no-access-log",
        ],
        stdout=log,
        stderr=log,
    )
    worker = subprocess.Popen([sys.executable, "-m", "invest.worker"], stdout=log, stderr=log)
    children.extend([web, worker])
    return web, worker


def until(fn, timeout=35):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = fn()
            if result:
                return result
        except (httpx.TransportError, KeyError, IndexError):
            pass
        time.sleep(0.1)
    raise AssertionError("Readiness/state transition timed out; inspect .local/restart.log")


with (root / ".local/restart.log").open("w") as log:
    try:
        web, worker = start(log)
        with httpx.Client(
            base_url="http://127.0.0.1:8012", headers={"Origin": os.environ["APP_ORIGIN"]}, timeout=3
        ) as client:
            until(lambda: client.get("/healthz").status_code == 200)
            response = client.post("/api/login", json={"username": "owner", "password": password})
            assert response.status_code == 200
            client.headers["X-CSRF-Token"] = response.json()["csrf"]
            until(lambda: client.get("/api/status").json()["worker"]["connected"])
            r = client.post("/api/research").json()
            c = next(c for c in r["candidates"] if c["id"] in r["shortlist"])
            payload = {
                "instrument_id": c["id"],
                "side": "buy",
                "mode": "demo-paper",
                "quantity": 5,
                "limit_price": round(c["price"] * 1.004, 2),
                "displayed_price": c["price"],
                "tolerance_pct": 0.5,
                "research_id": r["id"],
                "order_type": "limit",
                "session": "regular",
            }
            key = str(uuid.uuid4())
            response = client.post("/api/orders", json=payload, headers={"Idempotency-Key": key})
            assert response.status_code == 200, response.text
            order_id = response.json()["id"]
            partial = until(
                lambda: next(
                    (o for o in client.get("/api/orders").json() if o["status"] == "partially_filled"), None
                )
            )
            assert partial["filled"] == 3
            # Simulate an abrupt deploy/process loss, rather than a graceful HTTP client refresh.
            for proc in [worker, web]:
                proc.kill()
                proc.wait(timeout=10)
            with transaction() as db:
                assert db.get(models.Order, order_id).filled == 3
                assert db.get(models.Position, c["id"]).quantity == 3
            web, worker = start(log)
            until(lambda: client.get("/healthz").status_code == 200)
            # DB-backed session survives the web restart with the same server key.
            assert client.get("/api/session").status_code == 200
            replay = client.post("/api/orders", json=payload, headers={"Idempotency-Key": key})
            assert replay.status_code == 200 and replay.json()["id"] == order_id
            until(
                lambda: any(
                    o["id"] == order_id and o["status"] == "filled" for o in client.get("/api/orders").json()
                )
            )
            with transaction() as db:
                assert db.scalar(select(func.count()).select_from(models.Order)) == 1
                assert db.scalar(select(func.sum(models.Fill.quantity))) == 5
                assert db.scalar(select(func.count()).select_from(models.Fill)) == 2
                assert db.get(models.Position, c["id"]).quantity == 5
            print(
                "PASS: abrupt web/worker restart restored session, 3/5 partial fill and same order key; exactly 5 shares in 2 unique fills"
            )
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.kill()
