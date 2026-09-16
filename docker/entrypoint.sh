#!/bin/sh
# Chạy migration trước khi start server — thay cho Render "Pre-Deploy Command"
# (không hỗ trợ ở gói free, xem docs/deploy_render.md), và cũng chạy y hệt ở local
# docker compose. Idempotent: alembic tự kiểm bảng alembic_version, không có gì để
# upgrade thì thoát ngay, không lỗi.
set -e

uv run --no-sync alembic upgrade head

exec uv run --no-sync uvicorn src.api:app \
    --host 0.0.0.0 \
    --port 8010 \
    --workers 1 \
    --log-level info
