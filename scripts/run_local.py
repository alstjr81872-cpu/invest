"""Cross-platform local supervisor; use .venv's Python to invoke it."""

import os
import subprocess
import sys
import time
from pathlib import Path
from invest.config import settings

root = Path(__file__).resolve().parent.parent
os.chdir(root)
if not (root / ".env").is_file():
    raise SystemExit("First run scripts/init_local.py to create a private .env")
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
commands = [
    [sys.executable, "-m", "invest.worker"],
    [
        sys.executable,
        "-m",
        "uvicorn",
        "invest.api:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
        "--no-access-log",
    ],
]
if settings().free_tier:
    commands = commands[1:]
children = []
try:
    for command in commands:
        children.append(subprocess.Popen(command))
    print("Web started" + (" (manual free mode)." if settings().free_tier else " with independent worker."))
    while all(c.poll() is None for c in children):
        time.sleep(0.5)
except KeyboardInterrupt:
    pass
finally:
    for child in children:
        if child.poll() is None:
            child.terminate()
    for child in children:
        try:
            child.wait(timeout=20)
        except subprocess.TimeoutExpired:
            child.kill()
