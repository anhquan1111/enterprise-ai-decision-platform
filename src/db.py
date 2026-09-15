"""Truy cập PostgreSQL bằng raw SQL, không dùng ORM.

Lý do không ORM: tool SQL của hệ thống phải chạy những câu mà tác giả đọc được,
giải thích được và đọc được query plan. Mọi giá trị đi qua tham số của psycopg,
không nối vào chuỗi SQL.
"""

import atexit
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from src.config import get_settings

# Giai đoạn xác thực & độ tin cậy: pool thay vì mở connection mới mỗi lần gọi — chi
# phí mở connection mới đo được thật ở ngày 25 (vault, ~13ms/lần), nhỏ so với gọi
# Gemini nhưng không miễn phí, và
# là chi phí trả THÊM một lần nữa cho mỗi request khi không dùng lại.
#
# Singleton module-level có chủ ý: một pool dùng chung cho cả process, không phải
# một pool mới mỗi lần gọi get_connection() (sẽ triệt tiêu hoàn toàn lợi ích của
# pool). Giới hạn đã biết: pool được tạo bằng settings tại LẦN GỌI ĐẦU TIÊN; đổi
# settings sau đó (chỉ xảy ra trong test đổi biến môi trường DB, hiện không có test
# nào làm vậy) sẽ không làm pool tự cấu hình lại.
_DictConnection = psycopg.Connection[dict[str, Any]]
_pool: ConnectionPool[_DictConnection] | None = None


def _get_pool() -> ConnectionPool[_DictConnection]:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = ConnectionPool[_DictConnection](
            settings.database_url,
            min_size=settings.postgres_pool_min_size,
            max_size=settings.postgres_pool_max_size,
            kwargs={"row_factory": dict_row},
            open=True,
        )
        atexit.register(_pool.close)
    return _pool


@contextmanager
def get_connection(*, read_only: bool = True) -> Iterator[psycopg.Connection[dict[str, Any]]]:
    """Lấy một connection từ pool dùng chung, trả lại pool khi xong (không đóng hẳn).

    Args:
        read_only: Đặt cho PHIÊN GIAO DỊCH KẾ TIẾP trên connection này. Đường trả
            lời câu hỏi không bao giờ cần ghi dữ liệu nghiệp vụ, nên để read-only:
            một bug hoặc một câu SQL do LLM sinh ra cũng không sửa được dữ liệu.
            Ingestion và audit truyền False. Vì connection được TÁI SỬ DỤNG giữa các
            request, giá trị này phải đặt lại ở MỖI lần lấy connection — không được
            giả định connection còn giữ nguyên trạng thái từ lần dùng trước.

    Yields:
        Connection đang mở, row trả về dạng dict.
    """
    with _get_pool().connection() as conn:
        conn.read_only = read_only
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
