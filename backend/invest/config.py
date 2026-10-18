"""Server-only configuration. No secret values are included in API output."""

import os
from pathlib import Path
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    database_url: str
    origin: str
    owner: str
    password_hash: str
    session_secret: str
    secure_cookie: bool
    data_mode: str
    live_orders: bool
    worker_interval: int
    free_tier: bool = False


@lru_cache
def settings() -> Settings:
    load_dotenv(Path.cwd() / ".env", override=False)
    url = os.getenv("DATABASE_URL", "")
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    if not url.startswith("postgresql+psycopg://"):
        raise RuntimeError("DATABASE_URL must reference PostgreSQL; SQLite is not a production fallback")
    origin = (os.getenv("APP_ORIGIN") or os.getenv("RENDER_EXTERNAL_URL") or "http://127.0.0.1:8000").rstrip("/")
    secret = os.getenv("SESSION_SECRET", "")
    password = os.getenv("OWNER_PASSWORD_HASH", "")
    mode = os.getenv("DATA_MODE", "demo")
    if mode not in {"demo", "live-data"}:
        raise RuntimeError("DATA_MODE must be demo or live-data")
    secure = os.getenv("COOKIE_SECURE", "true").lower() == "true"
    if not secure and not origin.startswith(("http://127.0.0.1:", "http://localhost:")):
        raise RuntimeError("Insecure cookies are allowed only for local development")
    return Settings(
        url,
        origin,
        os.getenv("OWNER_USERNAME", "owner"),
        password,
        secret,
        secure,
        mode,
        os.getenv("ENABLE_LIVE_ORDERS", "false").lower() == "true",
        max(2, int(os.getenv("WORKER_INTERVAL_SECONDS", "5"))),
        os.getenv("FREE_TIER_MODE", "false").lower() == "true",
    )


def validate_web_config(config: Settings):
    if config.free_tier and (config.data_mode != "demo" or config.live_orders):
        raise RuntimeError("Free tier supports demo data and paper orders only")
    if len(config.session_secret) < 32 or not config.password_hash.startswith("$argon2id$"):
        raise RuntimeError("Set SESSION_SECRET (32+ characters) and OWNER_PASSWORD_HASH (Argon2id)")
    from urllib.parse import urlsplit

    parsed = urlsplit(config.origin)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError("APP_ORIGIN must be one exact HTTP(S) origin without path")
    if config.secure_cookie and parsed.scheme != "https":
        raise RuntimeError("Secure production cookies require an HTTPS APP_ORIGIN")
