import os

import pytest
from argon2 import PasswordHasher

os.environ["DATABASE_URL"] = os.getenv(
    "TEST_DATABASE_URL", "postgresql+psycopg://invest:local-development-only@127.0.0.1:55432/invest_test"
)
os.environ.update(
    APP_ORIGIN="https://testserver",
    COOKIE_SECURE="true",
    OWNER_USERNAME="owner",
    OWNER_PASSWORD_HASH=PasswordHasher().hash("test-password-only"),
    SESSION_SECRET="test-signing-secret-at-least-32-characters",
    DATA_MODE="demo",
    ENABLE_LIVE_ORDERS="false",
    FREE_TIER_MODE="false",
)

from invest.db import transaction, engine, utcnow
from invest.models import Base
from invest.service import bootstrap, ingest_quote
from invest.providers import demo


@pytest.fixture(scope="session", autouse=True)
def schema():
    from alembic.config import Config
    from alembic import command

    assert engine().url.database.endswith("_test"), "Refusing destructive tests outside a test database"
    command.upgrade(Config("alembic.ini"), "head")


@pytest.fixture(autouse=True)
def clean_db(schema):
    from sqlalchemy import text

    with transaction() as db:
        tables = ", ".join('"' + t.name + '"' for t in reversed(Base.metadata.sorted_tables))
        db.execute(text("TRUNCATE " + tables + " RESTART IDENTITY CASCADE"))
        bootstrap(db)
        for identifier, _, _, _, _, reference in demo.UNIVERSE:
            ingest_quote(db, identifier, demo.quote(identifier, reference, utcnow()))


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from invest.api import app

    with TestClient(app, base_url="https://testserver", headers={"Origin": "https://testserver"}) as client:
        yield client


@pytest.fixture
def owner(client):
    response = client.post("/api/login", json={"username": "owner", "password": "test-password-only"})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf"]
    return client


@pytest.fixture
def research(owner):
    response = owner.post("/api/research")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["shortlist"]
    return result


@pytest.fixture
def buy_request(research):
    c = next(c for c in research["candidates"] if c["id"] in research["shortlist"])
    return {
        "instrument_id": c["id"],
        "side": "buy",
        "mode": "demo-paper",
        "quantity": min(5, c["risk"]["quantity"]),
        "limit_price": round(c["price"] * 1.004, 2),
        "displayed_price": c["price"],
        "tolerance_pct": 0.5,
        "research_id": research["id"],
        "order_type": "limit",
        "session": "regular",
    }
