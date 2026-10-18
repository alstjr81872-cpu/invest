"""Run browser acceptance tests against an isolated PostgreSQL *_test database.

Never reads or clears the local owner database. Credentials exist only in child environments.
Requires an existing database named invest_e2e_test (or E2E_DATABASE_URL with *_test suffix).
"""

import os
import argparse
from pathlib import Path
import secrets
import subprocess
import sys
import time
import urllib.request

from argon2 import PasswordHasher
from sqlalchemy.engine import make_url

root = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument("--free", action="store_true", help="Validate manual free mode without a worker")
free_mode = parser.parse_args().free
os.chdir(root)
url = os.getenv(
    "E2E_DATABASE_URL", "postgresql+psycopg://invest:local-development-only@127.0.0.1:55432/invest_e2e_test"
)
if not make_url(url).database.endswith("_test"):
    raise SystemExit("Refusing to clear a database without the _test suffix")
port = int(os.getenv("E2E_PORT", "8011"))
password = secrets.token_urlsafe(24)
child_env = {
    **os.environ,
    "DATABASE_URL": url,
    "APP_ORIGIN": f"http://127.0.0.1:{port}",
    "COOKIE_SECURE": "false",
    "OWNER_USERNAME": "owner",
    "OWNER_PASSWORD_HASH": PasswordHasher().hash(password),
    "SESSION_SECRET": secrets.token_urlsafe(48),
    "DATA_MODE": "demo",
    "ENABLE_LIVE_ORDERS": "false",
    "WORKER_INTERVAL_SECONDS": "2",
    "E2E_PASSWORD": password,
    "E2E_BASE_URL": f"http://127.0.0.1:{port}",
    "FREE_TIER_MODE": "true" if free_mode else "false",
}
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], env=child_env, check=True)
# Clear only the isolated test DB through a separate subprocess to avoid loading .env settings here.
clean = """from invest.db import transaction,Base
from invest import models
from sqlalchemy import text
with transaction() as db:
 db.execute(text('TRUNCATE '+', '.join('"'+t.name+'"' for t in Base.metadata.sorted_tables)+' RESTART IDENTITY CASCADE'))
"""
subprocess.run([sys.executable, "-c", clean], env=child_env, check=True)
(root / ".local").mkdir(exist_ok=True)
children = []
exit_code = 1
with (root / ".local/e2e-services.log").open("w") as logs:
    try:
        if not free_mode:
            children.append(
                subprocess.Popen(
                    [sys.executable, "-m", "invest.worker"], env=child_env, stdout=logs, stderr=logs
                )
            )
        children.append(
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "invest.api:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--no-access-log",
                ],
                env=child_env,
                stdout=logs,
                stderr=logs,
            )
        )
        for _ in range(45):
            if any(c.poll() is not None for c in children):
                raise RuntimeError("Test services exited; inspect .local/e2e-services.log")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(1)
        else:
            raise RuntimeError("Test server readiness timed out")
        npm = "npm.cmd" if os.name == "nt" else "npm"
        spec = "free.spec.ts" if free_mode else "workflow.spec.ts"
        exit_code = subprocess.run(
            [npm, "run", "test:e2e", "--prefix", "frontend", "--", spec], env=child_env
        ).returncode
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                child.kill()
raise SystemExit(exit_code)
