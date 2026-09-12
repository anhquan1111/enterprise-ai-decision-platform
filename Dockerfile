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

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1

EXPOSE 8010

# /health is liveness only (no DB call) so a DB outage does not kill the
# container — readiness is a separate endpoint. See docs/decisions.md ADR-004.
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8010/health')" || exit 1

CMD ["uv", "run", "--no-sync", "uvicorn", "src.api:app", \
     "--host", "0.0.0.0", \
     "--port", "8010", \
     "--workers", "1", \
     "--log-level", "info"]
