"""Truy cập PostgreSQL bằng raw SQL, không dùng ORM.

Lý do không ORM: tool SQL của hệ thống phải chạy những câu mà tác giả đọc được,
giải thích được và đọc được query plan. Mọi giá trị đi qua tham số của psycopg,
không nối vào chuỗi SQL.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row

from src.config import get_settings


@contextmanager
def get_connection(*, read_only: bool = True) -> Iterator[psycopg.Connection[dict[str, Any]]]:
    """Mở connection dạng context manager.

    Args:
        read_only: Mở session chỉ đọc. Đường trả lời câu hỏi không bao giờ cần ghi
            dữ liệu nghiệp vụ, nên để read-only: một bug hoặc một câu SQL do LLM
            sinh ra cũng không sửa được dữ liệu. Ingestion và audit truyền False.

    Yields:
        Connection đang mở, row trả về dạng dict.
    """
    settings = get_settings()
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        if read_only:
            conn.read_only = True
        yield conn


def fetch_all(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Chạy một SELECT chỉ đọc và trả về toàn bộ dòng.

    Args:
        sql: Câu lệnh dùng named placeholder, ví dụ ``%(department)s``.
        params: Giá trị cho các placeholder đó.
    """
    with get_connection(read_only=True) as conn, conn.cursor() as cur:
        cur.execute(sql, params or {})
        return cur.fetchall()


def fetch_one(sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Như fetch_all nhưng trả về dòng đầu tiên, hoặc None nếu không có dòng nào."""
    with get_connection(read_only=True) as conn, conn.cursor() as cur:
        cur.execute(sql, params or {})
        return cur.fetchone()


def explain(sql: str, params: dict[str, Any] | None = None) -> str:
    """Trả về query plan thật (EXPLAIN ANALYZE) của một câu SELECT.

    ANALYZE nghĩa là câu lệnh được **chạy thật** để lấy số dòng và thời gian thực,
    không phải số ước lượng. Chỉ dùng cho SELECT.
    """
    with get_connection(read_only=True) as conn, conn.cursor() as cur:
        cur.execute(f"EXPLAIN (ANALYZE, BUFFERS) {sql}", params or {})
        return "\n".join(str(row["QUERY PLAN"]) for row in cur.fetchall())


def check_connection() -> str:
    """Trả về version của server, hoặc raise nếu database không tới được.

    Dùng cho readiness probe. Tách khỏi liveness probe để khi database chết thì
    service bị đánh dấu not-ready, chứ không bị restart container.
    """
    with get_connection(read_only=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT version() AS version")
        row = cur.fetchone()
        return str(row["version"]) if row else "unknown"
