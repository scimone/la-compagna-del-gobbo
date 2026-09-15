FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Applies to every `uv sync`/`uv run` below, not just the first one - `uv run` implicitly
# re-syncs the environment against pyproject.toml before running anything, which would
# otherwise silently pull dev-only tools (pytest, ruff) back in on the `collectstatic` step.
ENV UV_FROZEN=1 UV_NO_DEV=1

COPY pyproject.toml uv.lock ./
RUN uv sync

COPY . .

# collectstatic never touches the database, but importing config/settings.py unconditionally
# builds DATABASES from POSTGRES_* env vars - these placeholders exist only for this one build
# step (never baked into the image as a persistent ENV) and are overridden by the real values
# docker-compose supplies at container start.
RUN POSTGRES_DB=collectstatic POSTGRES_USER=collectstatic POSTGRES_PASSWORD=collectstatic \
    POSTGRES_HOST=collectstatic POSTGRES_PORT=5432 \
    uv run manage.py collectstatic --noinput
