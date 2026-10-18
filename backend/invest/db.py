from datetime import datetime, timezone
from functools import lru_cache
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session
from sqlalchemy.pool import NullPool

from .config import settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


@lru_cache
def engine():
    if settings().free_tier:
        # No idle pool heartbeat or reconnect loop: let Neon autosuspend.
        return create_engine(
            settings().database_url,
            poolclass=NullPool,
            connect_args={
                "connect_timeout": 10,
                "options": "-c statement_timeout=20000 -c lock_timeout=5000",
            },
        )
    return create_engine(
        settings().database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_recycle=300,
        connect_args={"connect_timeout": 10},
    )


@contextmanager
def transaction(*, isolation=None):
    bind = engine().execution_options(isolation_level=isolation) if isolation else engine()
    with Session(bind, expire_on_commit=False) as db:
        with db.begin():
            yield db
