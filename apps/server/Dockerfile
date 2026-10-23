FROM ghcr.io/astral-sh/uv:0.13.0 AS uv

FROM python:3.13.16-slim-trixie AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"
RUN python -m pip uninstall --yes --root-user-action ignore pip \
    && groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app
WORKDIR /app

FROM base AS api-build
COPY --from=uv /uv /usr/local/bin/uv
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-default-groups --no-install-project
COPY pyproject.toml uv.lock alembic.ini ./
COPY src ./src
COPY migrations ./migrations
COPY seeds ./seeds
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-default-groups --no-editable

FROM base AS worker-build
COPY --from=uv /uv /usr/local/bin/uv
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-default-groups --group render --no-install-project
COPY pyproject.toml uv.lock alembic.ini ./
COPY src ./src
COPY migrations ./migrations
COPY seeds ./seeds
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-default-groups --group render --no-editable

FROM base AS api
RUN apt-get update \
    && apt-get install --yes --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY --from=api-build --chown=app:app /app /app
COPY --chown=app:app tests/fixtures/compositions /app/golden
USER app
EXPOSE 8000
CMD ["uvicorn", "motionile.entrypoints.api:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-server-header"]

FROM base AS worker
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN apt-get update \
    && apt-get install --yes --no-install-recommends ffmpeg fonts-noto-core fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*
COPY --from=worker-build --chown=app:app /app /app
COPY --chown=app:app tests/fixtures/compositions /app/golden
RUN playwright install --with-deps chromium \
    && chown -R app:app /ms-playwright \
    && rm -rf /var/lib/apt/lists/*
USER app
CMD ["procrastinate", "--app=motionile.entrypoints.worker.app", "worker", "--queues=render", "--concurrency=1"]
