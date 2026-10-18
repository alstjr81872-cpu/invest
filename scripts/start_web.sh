#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python -m alembic upgrade head
exec python -m uvicorn invest.api:app --host 0.0.0.0 --port "${PORT:-8000}" --no-access-log --ws-max-size 1048576
