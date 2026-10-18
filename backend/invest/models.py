"""PostgreSQL is the source of truth for both web and worker processes."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import String, DateTime, Numeric, Integer, Boolean, ForeignKey, BigInteger, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, utcnow

Money = Numeric(20, 6)


def uid():
    return str(uuid.uuid4())


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    data_mode: Mapped[str] = mapped_column(String(20), default="demo", server_default="demo")
    cash: Mapped[Decimal] = mapped_column(Money, default=10000)
    initial_cash: Mapped[Decimal] = mapped_column(Money, default=10000)
    realized: Mapped[Decimal] = mapped_column(Money, default=0)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)
    version: Mapped[int] = mapped_column(default=0)


class Instrument(Base):
    __tablename__ = "instruments"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16))
    exchange: Mapped[str] = mapped_column(String(8))
    currency: Mapped[str] = mapped_column(default="USD")
    name: Mapped[str] = mapped_column(String(100))
    sector: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(default="common_stock")
    aliases: Mapped[list] = mapped_column(JSONB, default=list)
    __table_args__ = (UniqueConstraint("ticker", "exchange"),)


class Quote(Base):
    __tablename__ = "quotes"
    instrument_id: Mapped[str] = mapped_column(ForeignKey("instruments.id"), primary_key=True)
    last: Mapped[Decimal] = mapped_column(Money)
    bid: Mapped[Decimal | None] = mapped_column(Money)
    ask: Mapped[Decimal | None] = mapped_column(Money)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sequence: Mapped[int] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(64))
    quality: Mapped[dict] = mapped_column(JSONB)


class Dataset(Base):
    __tablename__ = "datasets"
    instrument_id: Mapped[str] = mapped_column(ForeignKey("instruments.id"), primary_key=True)
    bars: Mapped[list] = mapped_column(JSONB)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB)


class Recommendation(Base):
    __tablename__ = "recommendations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict] = mapped_column(JSONB)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    idempotency_key: Mapped[str] = mapped_column(String(80), unique=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    instrument_id: Mapped[str] = mapped_column(ForeignKey("instruments.id"))
    mode: Mapped[str] = mapped_column(default="demo-paper")
    side: Mapped[str] = mapped_column(String(4))
    status: Mapped[str] = mapped_column(default="accepted")
    quantity: Mapped[int] = mapped_column(Integer)
    filled: Mapped[int] = mapped_column(default=0)
    average_price: Mapped[Decimal] = mapped_column(Money, default=0)
    limit_price: Mapped[Decimal] = mapped_column(Money)
    displayed_price: Mapped[Decimal] = mapped_column(Money)
    reserved: Mapped[Decimal] = mapped_column(Money, default=0)
    fees: Mapped[Decimal] = mapped_column(Money, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    context: Mapped[dict] = mapped_column(JSONB, default=dict)
    broker_id: Mapped[str | None] = mapped_column(String(64))


class Fill(Base):
    __tablename__ = "fills"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    price: Mapped[Decimal] = mapped_column(Money)
    fee: Mapped[Decimal] = mapped_column(Money)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Position(Base):
    __tablename__ = "positions"
    instrument_id: Mapped[str] = mapped_column(ForeignKey("instruments.id"), primary_key=True)
    quantity: Mapped[int] = mapped_column(default=0)
    average_price: Mapped[Decimal] = mapped_column(Money, default=0)
    entry_fees: Mapped[Decimal] = mapped_column(Money, default=0)
    entry_fx: Mapped[Decimal] = mapped_column(Money, default=1350)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    version: Mapped[int] = mapped_column(default=1)
    original: Mapped[dict] = mapped_column(JSONB)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    dedup_key: Mapped[str] = mapped_column(String(100), unique=True)
    kind: Mapped[str] = mapped_column(String(30))
    state: Mapped[str] = mapped_column(default="queued")
    payload: Mapped[dict] = mapped_column(JSONB)
    result: Mapped[dict | None] = mapped_column(JSONB)
    attempts: Mapped[int] = mapped_column(default=0)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(160), unique=True)
    kind: Mapped[str] = mapped_column(String(30))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    payload: Mapped[dict] = mapped_column(JSONB)


class WorkerState(Base):
    __tablename__ = "worker_state"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    heartbeat: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[dict] = mapped_column(JSONB)


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    failures: Mapped[int] = mapped_column(default=0)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    csrf: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class UsageBudget(Base):
    __tablename__ = "usage_budgets"
    period: Mapped[str] = mapped_column(String(20), primary_key=True)
    counters: Mapped[dict] = mapped_column(JSONB, default=dict)
