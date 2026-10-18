#!/usr/bin/env bash
# Reproduce dependencies in the existing isolated cloud checkout, without a worktree.
set -euo pipefail
cd /workspace/invest
export UV_CACHE_DIR=/workspace/.uv-cache
export UV_PYTHON_INSTALL_DIR=/workspace/.tools/python
export npm_config_cache=/workspace/.npm-cache
python3 - <<'PY'
from pathlib import Path
import hashlib
import subprocess
import tarfile
import urllib.request

version = Path('.node-version').read_text().strip()
root = Path('/workspace/.tools/node')
name = f'node-v{version}-linux-x64'
binary = root / name / 'bin/node'
if binary.exists() and subprocess.check_output([binary], text=True, input='console.log(process.version)').strip() == f'v{version}':
    raise SystemExit(0)
root.mkdir(parents=True, exist_ok=True)
base = f'https://nodejs.org/dist/v{version}/'
archive = root / f'{name}.tar.xz'
with urllib.request.urlopen(base + 'SHASUMS256.txt', timeout=30) as response:
    checks = response.read().decode()
expected = next(line.split()[0] for line in checks.splitlines() if line.split()[-1] == archive.name)
if not archive.exists():
    with urllib.request.urlopen(base + archive.name, timeout=60) as response:
        archive.write_bytes(response.read())
if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
    raise SystemExit('Official Node SHA256 verification failed; artifact not used')
with tarfile.open(archive) as tar:
    tar.extractall(root, filter='data')
PY
export PATH="/workspace/.tools/node/node-v$(cat .node-version)-linux-x64/bin:$PATH"
uv sync --frozen --python 3.12.14
npm ci --prefix frontend --no-audit --no-fund
npm run build --prefix frontend
echo 'Cloud dependencies and production frontend are installed; start PostgreSQL, migrate, then start web/worker.'
