# syntax=docker/dockerfile:1
# ─────────────────────────────────────────────────────────────
# Enterprise AI Decision Platform — API image
# Port: 8010
# No model weights are baked in; embeddings/LLM are configured via env vars.
# ─────────────────────────────────────────────────────────────

FROM python:3.12-slim

# Install uv (fast Python package manager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Dependencies first so code changes do not invalidate the install layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src/ ./src/
COPY sql/ ./sql/
# Migration tooling (ADR-025) — cần cả 2 để "alembic upgrade head" chạy được lúc
# container khởi động (xem docker/entrypoint.sh), kể cả trên Render free tier vốn
# không hỗ trợ Pre-Deploy Command riêng (docs/deploy_render.md).
COPY alembic.ini ./alembic.ini
COPY alembic/ ./alembic/
# Giao diện demo tĩnh (/ui) — HTML/CSS/JS thuần, không build step. StaticFiles đòi
# thư mục này TỒN TẠI ngay lúc app khởi động (app.mount trong src/api.py), thiếu
# COPY này thì container crash ngay khi start, không phải lỗi 404 êm ái. ADR-029.
COPY web/ ./web/
COPY docker/entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1

EXPOSE 8010

# /health is liveness only (no DB call) so a DB outage does not kill the
# container — readiness is a separate endpoint. See docs/decisions.md ADR-004.
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8010/health')" || exit 1

CMD ["./entrypoint.sh"]
