# syntax=docker/dockerfile:1.7
#
# Stages: frontend → base → test (for `make test-backend`) and runtime.
# `runtime` must stay the LAST stage: `docker build .` and `docker compose up --build` build the last stage
# unless a target is named.

# ---- frontend: build the React app -------------------------------------------------------------
FROM node:24-slim AS frontend
WORKDIR /build/frontend
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN --mount=type=cache,id=pnpm-store,target=/pnpm-store \
    pnpm config set store-dir /pnpm-store && pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

# ---- base: Python, dependencies and the backend code ----------------------------------------------
FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /usr/local/bin/uv
WORKDIR /app

# Dependencies first (cached unless the lockfile changes), then the project itself.
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra postgres --no-install-project
COPY backend/ ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra postgres
RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir -p /data && chown app:app /data

# ---- test: `docker build --target test -t resume-tailor:test . && docker run --rm resume-tailor:test`
FROM base AS test
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --extra dev --extra postgres
COPY schema/ /schema/
USER app
CMD ["pytest", "-p", "no:cacheprovider"]

# ---- runtime: FastAPI app serving the API and the built frontend (the default build target) -------
FROM base AS runtime
COPY --from=frontend /build/frontend/dist /app/static
USER app
ENV DATA_DIR=/data \
    STATIC_DIR=/app/static
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn --factory app.main:create_app --host 0.0.0.0 --port 8080 --proxy-headers --forwarded-allow-ips=\"${TRUSTED_PROXIES:-127.0.0.1}\""]
