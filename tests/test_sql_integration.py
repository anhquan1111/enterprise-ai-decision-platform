"""Integration test: cần PostgreSQL đang chạy và đã ingest corpus.

Chuẩn bị:
    docker compose up -d db
    docker compose exec -T db psql -U app -d enterprise_ai -f /sql/01_schema.sql
    docker compose exec -T db psql -U app -d enterprise_ai -f /sql/02_seed.sql
    uv run python -m scripts.ingest

Chạy:
    uv run pytest tests/ -m integration

Bị loại khỏi suite mặc định nên CI vẫn xanh khi không có database.
"""

import pytest

from src.contracts import visible_access_levels
from src.db import fetch_all, fetch_one, get_connection

pytestmark = pytest.mark.integration

AS_OF = "2026-09-01 00:00+00"


def test_join_to_departments_does_not_multiply_rows() -> None:
    """JOIN many-to-one không được làm tăng số dòng.

    departments có khóa chính trên department nên mỗi dòng doanh thu khớp đúng một
    dòng. Đây là điều phải kiểm, không phải giả định: một khóa trùng ở bảng bên kia sẽ
    nhân bản dòng mà query vẫn chạy bình thường và không báo lỗi nào.
    """
    before = fetch_one("SELECT COUNT(*) AS n FROM monthly_revenue")
    after = fetch_one(
        """
        SELECT COUNT(*) AS n
        FROM monthly_revenue r
        JOIN departments d ON d.department = r.department
        """
    )

    assert before is not None and after is not None
    assert before["n"] == after["n"] == 24


def test_month_grain_has_one_row_per_department_month() -> None:
    dups = fetch_all(
        """
        SELECT department, month, COUNT(*) AS n
        FROM monthly_revenue
        GROUP BY department, month
        HAVING COUNT(*) > 1
        """
    )

    assert dups == []


def test_mom_growth_is_negative_where_revenue_dropped() -> None:
    """Sales tháng 3 giảm so với tháng 2, nên tăng trưởng phải ra số âm.

    Seed gài sẵn một tháng giảm để window function có chỗ sai lộ ra: nếu thiếu
    PARTITION BY hoặc sai ORDER BY thì con số này sẽ không âm.
    """
    rows = fetch_all(
        """
        SELECT month,
               revenue_vnd,
               LAG(revenue_vnd) OVER (PARTITION BY department ORDER BY month) AS prev
        FROM monthly_revenue
        WHERE department = 'sales'
        ORDER BY month
        """
    )
    by_month = {str(r["month"]): r for r in rows}

    assert by_month["2026-01-01"]["prev"] is None
    assert by_month["2026-03-01"]["revenue_vnd"] < by_month["2026-03-01"]["prev"]


def test_employee_sees_fewer_chunks_than_executive() -> None:
    """Cùng một phòng ban, role cao hơn thấy nhiều chunk hơn.

    Đây là bản nháp của test cách ly quyền sẽ hoàn thiện ở D4. Ở D1 nó đã chứng minh
    được một điều: phạm vi quyền áp được bằng filter ở tầng truy vấn.
    """
    sql = """
        SELECT COUNT(*) AS n
        FROM doc_chunks
        WHERE department = 'finance'
          AND access_level = ANY(%(levels)s)
          AND available_at <= %(as_of)s
    """
    emp = fetch_one(sql, {"levels": visible_access_levels("employee"), "as_of": AS_OF})
    exe = fetch_one(sql, {"levels": visible_access_levels("executive"), "as_of": AS_OF})

    assert emp is not None and exe is not None
    assert emp["n"] < exe["n"]


def test_unknown_role_retrieves_nothing() -> None:
    """Role lạ không lấy được chunk nào: danh sách mức quyền rỗng thì ANY() không khớp."""
    rows = fetch_all(
        """
        SELECT doc_id FROM doc_chunks
        WHERE department = 'finance' AND access_level = ANY(%(levels)s)
        """,
        {"levels": visible_access_levels("nguoi_la")},
    )

    assert rows == []


def test_point_in_time_hides_documents_not_yet_available() -> None:
    """Tài liệu có available_at sau mốc as_of thì không được trả về.

    SAL-009 (chính sách giảm giá nửa cuối 2026) available_at là 25/06/2026, nên truy
    vấn ở mốc 01/06/2026 không được thấy nó.
    """
    early = fetch_all(
        """
        SELECT doc_id FROM doc_chunks
        WHERE department = 'sales' AND available_at <= '2026-06-01 00:00+00'
        """
    )
    later = fetch_all(
        """
        SELECT doc_id FROM doc_chunks
        WHERE department = 'sales' AND available_at <= '2026-07-01 00:00+00'
        """
    )

    assert "SAL-009" not in {r["doc_id"] for r in early}
    assert "SAL-009" in {r["doc_id"] for r in later}


def test_expired_document_is_excluded_by_effective_window() -> None:
    """SAL-002 hết hiệu lực 30/06/2026, nên không còn trả về ở mốc tháng 9."""
    rows = fetch_all(
        """
        SELECT doc_id FROM doc_chunks
        WHERE department = 'sales'
          AND effective_from <= %(as_of)s::date
          AND (effective_to IS NULL OR effective_to >= %(as_of)s::date)
        """,
        {"as_of": AS_OF},
    )

    assert "SAL-002" not in {r["doc_id"] for r in rows}


def test_database_rejects_bad_row_even_without_python_layer() -> None:
    """Constraint là lớp chặn thứ hai: ghi trực tiếp vẫn bị từ chối.

    Lớp Python chỉ bảo vệ được đường đi qua nó. Constraint chặn cả script migration
    hay một lần sửa tay lúc xử lý sự cố.
    """
    import psycopg

    with (
        pytest.raises(psycopg.errors.CheckViolation),
        get_connection(read_only=False) as conn,
        conn.cursor() as cur,
    ):
        cur.execute(
            """
                INSERT INTO doc_chunks (
                    doc_id, chunk_index, department, access_level, title, chunk_text,
                    published_at, available_at, effective_from,
                    source_file, source_hash, contract_version, ingested_at
                ) VALUES (
                    'TEST-BAD', 0, 'finance', 'top_secret', 't', 'x',
                    now(), now(), '2026-01-01', 'test', 'test', '1.0.0', now()
                )
            """
        )


def test_ingest_run_rows_must_balance() -> None:
    """Manifest phải cân: nhận + loại = số dòng trong file.

    Constraint ck_rows_balance ép điều đó ở tầng database, nên một batch có dòng biến
    mất không thể ghi được manifest.
    """
    unbalanced = fetch_all(
        """
        SELECT run_id FROM ingest_run
        WHERE rows_accepted + rows_quarantined <> rows_in_file
        """
    )

    assert unbalanced == []


def test_every_quarantined_row_has_a_reason() -> None:
    rows = fetch_all(
        "SELECT quarantine_id FROM doc_chunks_quarantine WHERE btrim(reject_reason) = ''"
    )

    assert rows == []


_UPSERT_SQL = """
    INSERT INTO doc_chunks (
        doc_id, chunk_index, department, access_level, title, chunk_text,
        published_at, available_at, effective_from, effective_to,
        source_file, source_hash, contract_version, ingested_at
    ) VALUES (
        %(doc_id)s, 0, 'hr', 'employee', 'test', %(chunk_text)s,
        now(), now(), '2026-01-01', NULL,
        'test.csv', 'testhash', 'v1', now()
    )
    ON CONFLICT (doc_id, chunk_index) DO UPDATE SET
        chunk_text = EXCLUDED.chunk_text,
        ingested_at = EXCLUDED.ingested_at,
        embedding = CASE
            WHEN doc_chunks.chunk_text IS DISTINCT FROM EXCLUDED.chunk_text
            THEN NULL
            ELSE doc_chunks.embedding
        END
"""


def test_reingest_invalidates_embedding_only_when_text_actually_changes() -> None:
    """scripts/ingest.py: đổi chunk_text mà không reset embedding thì retrieval xếp
    hạng theo vector của văn bản CŨ trong khi trả về trích dẫn của văn bản MỚI — hai
    thứ không còn khớp nhau. Vá bằng CASE trong ON CONFLICT DO UPDATE; test này khoá
    lại đúng hành vi đó bằng một doc_id giả lập, không đụng corpus thật."""
    doc_id = "TEST-EMBED-INVALIDATION"
    try:
        with get_connection(read_only=False) as conn, conn.cursor() as cur:
            cur.execute(_UPSERT_SQL, {"doc_id": doc_id, "chunk_text": "van ban goc"})
            cur.execute(
                "UPDATE doc_chunks SET embedding = array_fill(0.1, ARRAY[384])::vector "
                "WHERE doc_id = %(doc_id)s AND chunk_index = 0",
                {"doc_id": doc_id},
            )
            conn.commit()

        # Ingest lại với ĐÚNG văn bản cũ — embedding phải được giữ nguyên.
        with get_connection(read_only=False) as conn, conn.cursor() as cur:
            cur.execute(_UPSERT_SQL, {"doc_id": doc_id, "chunk_text": "van ban goc"})
            conn.commit()
        row = fetch_one(
            "SELECT embedding IS NOT NULL AS has_embedding FROM doc_chunks "
            "WHERE doc_id = %(doc_id)s AND chunk_index = 0",
            {"doc_id": doc_id},
        )
        assert row is not None and row["has_embedding"] is True

        # Ingest lại với văn bản KHÁC — embedding phải bị reset về NULL.
        with get_connection(read_only=False) as conn, conn.cursor() as cur:
            cur.execute(_UPSERT_SQL, {"doc_id": doc_id, "chunk_text": "van ban da doi"})
            conn.commit()
        row = fetch_one(
            "SELECT embedding IS NOT NULL AS has_embedding FROM doc_chunks "
            "WHERE doc_id = %(doc_id)s AND chunk_index = 0",
            {"doc_id": doc_id},
        )
        assert row is not None and row["has_embedding"] is False
    finally:
        with get_connection(read_only=False) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM doc_chunks WHERE doc_id = %(doc_id)s", {"doc_id": doc_id})
            conn.commit()
