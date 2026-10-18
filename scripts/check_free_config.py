"""Read-only free deployment checks. Never print URLs, hashes or credentials."""

import argparse

from sqlalchemy import text
from sqlalchemy.engine import make_url

from invest.config import settings, validate_web_config


def validate(config, *, local=False):
    validate_web_config(config)
    if not config.free_tier:
        raise ValueError("FREE_TIER_MODE=true is required")
    if local:
        if make_url(config.database_url).host not in {"localhost", "127.0.0.1"}:
            raise ValueError("--local is restricted to a loopback database")
        return
    url = make_url(config.database_url)
    if not (url.host or "").endswith(".neon.tech") or "-pooler" in url.host:
        raise ValueError("Use a Neon direct connection, not a pooled endpoint")
    if url.query.get("sslmode") != "verify-full" or url.query.get("sslrootcert") != "system":
        raise ValueError("Require sslmode=verify-full and sslrootcert=system")
    if url.query.get("channel_binding") != "require":
        raise ValueError("Require channel_binding=require")
    if not config.origin.startswith("https://") or not config.secure_cookie:
        raise ValueError("Production requires HTTPS and Secure cookies")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", action="store_true", help="Connect once to verify TLS, schema and size")
    parser.add_argument("--local", action="store_true", help="Allow loopback DB for development verification")
    args = parser.parse_args()
    try:
        validate(settings(), local=args.local)
    except (ValueError, RuntimeError):
        raise SystemExit(
            "Free configuration failed. Check mode, Neon DIRECT URL/TLS, owner hash, session secret and HTTPS origin. No values printed."
        ) from None
    if args.database:
        from invest.db import transaction
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        try:
            with transaction() as db:
                if not args.local and not db.scalar(
                    text("SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()")
                ):
                    raise RuntimeError("TLS required")
                expected = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
                if db.scalar(text("SELECT version_num FROM alembic_version")) != expected:
                    raise RuntimeError("Migration required")
                if db.scalar(text("SELECT pg_database_size(current_database())")) >= 300_000_000:
                    raise RuntimeError("Storage limit")
        except Exception:
            raise SystemExit(
                "Database check failed. Verify network, DIRECT/TLS connection, current migrations and storage. No connection values printed."
            ) from None
        print("Database connection, schema and storage checks passed.")
    print(
        "Free app configuration passed. Provider Free plans, payment settings and actual usage still require account verification."
    )


if __name__ == "__main__":
    main()
