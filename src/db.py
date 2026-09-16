"""Quản lý kết nối PostgreSQL bằng raw SQL thuần (psycopg 3) và Connection Pool, không dùng ORM."""

import atexit
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from src.config import get_settings

# ── 1. Khởi tạo Connection Pool (Singleton) ──────────────
_DictConnection = psycopg.Connection[dict[str, Any]]
_pool: ConnectionPool[_DictConnection] | None = None


def _get_pool() -> ConnectionPool[_DictConnection]:
    """Tạo hoặc tái sử dụng một Connection Pool duy nhất cho toàn bộ process (Singleton)."""
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = ConnectionPool[_DictConnection](
            settings.database_url,
            min_size=settings.postgres_pool_min_size,
            max_size=settings.postgres_pool_max_size,
            kwargs={"row_factory": dict_row},  # Trả dữ liệu dạng dict thay vì tuple
            open=True,
        )
        atexit.register(_pool.close)  # Tự động đóng sạch pool khi ứng dụng tắt
    return _pool


# ── 2. Context Manager lấy kết nối an toàn ───────────────
@contextmanager
def get_connection(*, read_only: bool = True) -> Iterator[psycopg.Connection[dict[str, Any]]]:
    """Mượn một kết nối từ pool và tự động trả lại sau khi dùng xong (Context Manager).

    Mặc định read_only=True để phòng vệ: dù có lỗi code hay prompt injection cũng không sửa được DB.
    """
    with _get_pool().connection() as conn:
        conn.read_only = read_only  # Phải gán lại mỗi lần mượn vì connection được tái sử dụng
        yield conn


# ── 3. Các hàm thực thi truy vấn tiện ích ────────────────
def fetch_all(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Chạy câu lệnh SELECT chỉ đọc và trả về toàn bộ các dòng dưới dạng list[dict]."""
    with get_connection(read_only=True) as conn, conn.cursor() as cur:
        cur.execute(sql, params or {})
        return cur.fetchall()


def fetch_one(sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Chạy câu lệnh SELECT và trả về dòng đầu tiên, hoặc None nếu không có kết quả."""
    with get_connection(read_only=True) as conn, conn.cursor() as cur:
        cur.execute(sql, params or {})
        return cur.fetchone()


def explain(sql: str, params: dict[str, Any] | None = None) -> str:
    """Chạy EXPLAIN (ANALYZE, BUFFERS) thật để đo đạc thời gian và kế hoạch thực thi câu lệnh."""
    with get_connection(read_only=True) as conn, conn.cursor() as cur:
        cur.execute(f"EXPLAIN (ANALYZE, BUFFERS) {sql}", params or {})
        return "\n".join(str(row["QUERY PLAN"]) for row in cur.fetchall())


def check_connection() -> str:
    """Kiểm tra server DB còn sống không (dùng riêng cho endpoint /ready, tách biệt /health)."""
    with get_connection(read_only=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT version() AS version")
        row = cur.fetchone()
        return str(row["version"]) if row else "unknown"
