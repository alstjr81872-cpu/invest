#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python -m pip install --require-hashes -r requirements.txt
python -m pip install --no-deps .
