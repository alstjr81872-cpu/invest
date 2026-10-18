# syntax=docker/dockerfile:1
# Optional CA secret mounts are used only by managed development environments.
# Render builds use the image's normal CA roots and require no build secrets.
FROM node:22.22.0-bookworm-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/proxy_ca; fi; \
    npm ci --strict-ssl=true --no-audit --no-fund
COPY frontend/index.html frontend/tsconfig.json frontend/vite.config.ts ./
COPY frontend/src ./src
RUN npm run build

FROM python:3.12.14-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt ./
RUN --mount=type=secret,id=system_ca \
    if [ -f /run/secrets/system_ca ]; then export PIP_CERT=/run/secrets/system_ca; fi; \
    python -m pip install --no-cache-dir --require-hashes -r requirements.txt
COPY pyproject.toml ./
COPY backend/invest ./backend/invest
RUN --mount=type=secret,id=system_ca \
    if [ -f /run/secrets/system_ca ]; then export PIP_CERT=/run/secrets/system_ca; fi; \
    python -m pip install --no-cache-dir --no-deps .
COPY alembic.ini ./
COPY migrations ./migrations
COPY --from=frontend /build/frontend/dist ./frontend/dist
RUN chmod -R a+rX /app
USER 10001:10001
EXPOSE 8000
# Free deployment uses only this web container with FREE_TIER_MODE=true.
# Web startup includes migration; no paid pre-deploy service or worker is needed.
CMD ["sh", "-c", "python -m alembic upgrade head && exec python -m uvicorn invest.api:app --host 0.0.0.0 --port \"${PORT:-8000}\" --no-access-log --ws-max-size 1048576"]
