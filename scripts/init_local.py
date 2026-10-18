"""Create an ignored local config. Never overwrite an existing .env."""

import getpass
import secrets
from pathlib import Path
from argon2 import PasswordHasher

root = Path(__file__).resolve().parent.parent
path = root / ".env"
if path.exists():
    raise SystemExit(".env exists; edit it securely rather than overwriting it")
password = getpass.getpass("Local owner password (12+ characters): ")
if len(password) < 12:
    raise SystemExit("Use 12 or more characters")
content = "\n".join(
    [
        "DATABASE_URL=postgresql+psycopg://invest:local-development-only@127.0.0.1:55432/invest",
        "APP_ORIGIN=http://127.0.0.1:8000",
        "OWNER_USERNAME=owner",
        "OWNER_PASSWORD_HASH='" + PasswordHasher().hash(password) + "'",
        "SESSION_SECRET=" + secrets.token_urlsafe(48),
        "COOKIE_SECURE=false",
        "DATA_MODE=demo",
        "ENABLE_LIVE_ORDERS=false",
        "WORKER_INTERVAL_SECONDS=5",
        "",
    ]
)
path.write_text(content, encoding="utf-8")
path.chmod(0o600)
print("Created ignored .env; local owner configured. No credentials printed.")
