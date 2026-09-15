"""baseline schema

Chụp lại đúng trạng thái schema hiện có (sql/00_extensions.sql + sql/01_schema.sql
+ sql/06_auth.sql) làm điểm khởi đầu cho Alembic — dự án đã chạy production-shaped
từ trước khi có migration tool, nên "baseline" ở đây nghĩa là "mô tả lại cái đã có",
không phải "bắt đầu từ rỗng". Từ migration TIẾP THEO trở đi mới là nơi mọi thay đổi
schema thật sự đi qua Alembic.

Cố ý chép nguyên văn SQL vào đây thay vì đọc lại sql/*.sql lúc chạy: một migration
phải là ảnh chụp bất biến của một thời điểm — nếu sql/01_schema.sql đổi sau này (nó
sẽ đổi, mỗi khi có ADR mới), migration này không được đổi theo, nếu không lịch sử
migrate sẽ không còn tái lập đúng được nữa. sql/01_schema.sql tự nó không bị xoá:
vẫn là cách nhanh nhất để dựng một DB dev sạch từ đầu (xem AGENTS.md), Alembic chỉ
quản lý các thay đổi TIẾP THEO trên một DB đã tồn tại.

Revision ID: 9064d9299cfa
Revises:
Create Date: 2026-09-15 23:39:41.833463

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9064d9299cfa"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── sql/00_extensions.sql ──────────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # ── sql/01_schema.sql ───────────────────────────────────────────────
    op.execute("""
        CREATE TABLE departments (
            department  TEXT PRIMARY KEY,
            full_name   TEXT NOT NULL,
            CONSTRAINT ck_department_known
                CHECK (department IN ('sales', 'hr', 'finance', 'engineering'))
        )
    """)

    op.execute("""
        CREATE TABLE employees (
            employee_id TEXT PRIMARY KEY,
            full_name   TEXT NOT NULL,
            department  TEXT NOT NULL REFERENCES departments (department),
            role        TEXT NOT NULL,
            CONSTRAINT ck_employee_role
                CHECK (role IN ('employee', 'manager', 'executive'))
        )
    """)

    op.execute("""
        CREATE TABLE monthly_revenue (
            department      TEXT    NOT NULL REFERENCES departments (department),
            month           DATE    NOT NULL,
            revenue_vnd     BIGINT  NOT NULL,
            is_final        BOOLEAN NOT NULL DEFAULT TRUE,
            CONSTRAINT pk_monthly_revenue PRIMARY KEY (department, month),
            CONSTRAINT ck_revenue_nonneg CHECK (revenue_vnd >= 0),
            CONSTRAINT ck_month_is_first_day CHECK (month = date_trunc('month', month)::date)
        )
    """)

    op.execute("""
        CREATE TABLE doc_chunks (
            doc_id            TEXT        NOT NULL,
            chunk_index       INTEGER     NOT NULL,
            department        TEXT        NOT NULL REFERENCES departments (department),
            access_level      TEXT        NOT NULL,
            title             TEXT        NOT NULL,
            chunk_text        TEXT        NOT NULL,
            published_at      TIMESTAMPTZ NOT NULL,
            available_at      TIMESTAMPTZ NOT NULL,
            effective_from    DATE        NOT NULL,
            effective_to      DATE,
            embedding         vector(384),
            source_file       TEXT        NOT NULL,
            source_hash       TEXT        NOT NULL,
            contract_version  TEXT        NOT NULL,
            ingested_at       TIMESTAMPTZ NOT NULL,
            CONSTRAINT pk_doc_chunks PRIMARY KEY (doc_id, chunk_index),
            CONSTRAINT ck_access_level
                CHECK (access_level IN ('employee', 'manager', 'executive')),
            CONSTRAINT ck_interval_direction
                CHECK (effective_to IS NULL OR effective_from <= effective_to),
            CONSTRAINT ck_timestamp_order
                CHECK (available_at >= published_at),
            CONSTRAINT ck_text_not_blank
                CHECK (length(btrim(chunk_text)) > 0)
        )
    """)

    op.execute("""
        CREATE TABLE doc_chunks_quarantine (
            quarantine_id     BIGSERIAL   PRIMARY KEY,
            doc_id            TEXT,
            chunk_index       INTEGER,
            raw_row           JSONB       NOT NULL,
            reject_reason     TEXT        NOT NULL,
            source_file       TEXT        NOT NULL,
            source_hash       TEXT        NOT NULL,
            contract_version  TEXT        NOT NULL,
            ingested_at       TIMESTAMPTZ NOT NULL
        )
    """)

    op.execute("""
        CREATE TABLE ingest_run (
            run_id            BIGSERIAL   PRIMARY KEY,
            source_file       TEXT        NOT NULL,
            source_hash       TEXT        NOT NULL,
            contract_version  TEXT        NOT NULL,
            rows_in_file      INTEGER     NOT NULL,
            rows_accepted     INTEGER     NOT NULL,
            rows_quarantined  INTEGER     NOT NULL,
            rows_inserted     INTEGER     NOT NULL,
            rows_updated      INTEGER     NOT NULL,
            violations        JSONB       NOT NULL,
            started_at        TIMESTAMPTZ NOT NULL,
            finished_at       TIMESTAMPTZ NOT NULL,
            CONSTRAINT ck_rows_balance
                CHECK (rows_accepted + rows_quarantined = rows_in_file)
        )
    """)

    op.execute("""
        CREATE TABLE audit_log (
            audit_id          BIGSERIAL   PRIMARY KEY,
            request_id        UUID        NOT NULL,
            user_id           TEXT        NOT NULL,
            role              TEXT        NOT NULL,
            department        TEXT        NOT NULL,
            question          TEXT        NOT NULL,
            tool_used         TEXT        NOT NULL,
            retrieved_doc_ids TEXT[]      NOT NULL DEFAULT '{}',
            abstained         BOOLEAN     NOT NULL,
            llm_model         TEXT,
            total_tokens      INTEGER,
            latency_ms        INTEGER     NOT NULL,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    op.execute(
        "CREATE INDEX ix_chunks_scope ON doc_chunks (department, access_level, available_at)"
    )

    # ── sql/06_auth.sql ─────────────────────────────────────────────────
    op.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS api_key_hash TEXT")
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_employees_api_key_hash
            ON employees (api_key_hash)
            WHERE api_key_hash IS NOT NULL
    """)


def downgrade() -> None:
    # Đúng thứ tự ngược của sql/01_schema.sql's DROP list — con trước cha theo
    # foreign key, index đi cùng bảng chứa nó nên không cần DROP INDEX riêng.
    op.execute("DROP TABLE IF EXISTS audit_log")
    op.execute("DROP TABLE IF EXISTS ingest_run")
    op.execute("DROP TABLE IF EXISTS doc_chunks_quarantine")
    op.execute("DROP TABLE IF EXISTS doc_chunks")
    op.execute("DROP TABLE IF EXISTS monthly_revenue")
    op.execute("DROP TABLE IF EXISTS employees")
    op.execute("DROP TABLE IF EXISTS departments")
    # Không drop extension (vector, pg_trgm): một database có thể có dữ liệu khác
    # đang dùng chung extension đó, và DROP EXTENSION không phải thao tác an toàn để
    # tự động hoá trong một downgrade.
