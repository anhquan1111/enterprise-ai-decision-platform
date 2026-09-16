"""Triển khai hai công cụ của Agent: truy vấn số liệu SQL và tìm kiếm tài liệu quy trình.

Kiểm tra quyền hạn RBAC trước khi thực thi; phân biệt rõ lỗi hạ tầng và lỗi nghiệp vụ.
"""

from pathlib import Path

import httpx

from src.db import fetch_all
from src.retrieval import RetrievedChunk, retrieve
from src.scope import can_compare_departments, can_query_department

from .schema import SqlArgs

# 1. Định Nghĩa Ngoại Lệ & Lỗi Công Cụ (Custom Tool Exceptions)

_SQL_DIR = Path(__file__).parent.parent.parent / "sql"
_SQL_SINGLE_DEPARTMENT = (_SQL_DIR / "03_business_metrics.sql").read_text(encoding="utf-8")
_SQL_COMPARE_DEPARTMENTS = (_SQL_DIR / "08_business_metrics_compare.sql").read_text(
    encoding="utf-8"
)


class ToolPermissionError(Exception):
    """Ngoại lệ khi vi phạm RBAC: vai trò hoặc phòng ban của người gọi không được phép xem.

    Tách riêng với ToolExecutionError: đây là lỗi từ chối quyền (access_correct), không phải
    lỗi thiếu dữ liệu (no_knowledge_correct). Hai lỗi này ứng với hai nhãn kiểm toán khác nhau.
    """


class ToolExecutionError(Exception):
    """Ngoại lệ nghiệp vụ: tham số truy vấn hợp lệ nhưng cơ sở dữ liệu không có dòng nào khớp.

    Lỗi này không được retry vì thử lại với cùng tham số trên dữ liệu tĩnh chắc chắn vẫn rỗng.
    """


# 2. Công Cụ Truy Vấn Số Liệu Doanh Thu (sql_tool)


def sql_tool(args: SqlArgs, *, role: str, caller_department: str) -> tuple[str, list[dict]]:
    """Thực thi MỘT trong hai truy vấn SQL cố định (chọn theo `args.query_type`) và trả về
    (văn bản định dạng, danh sách bản ghi thô).

    Bảo mật Pre-execution RBAC: Kiểm tra quyền TRƯỚC KHI gửi lệnh vào database. Tuyệt đối
    không để database chạy truy vấn rồi mới lọc kết quả ở RAM, ngăn rò rỉ dữ liệu mật.
    """
    if args.query_type == "compare_departments":
        return _run_compare_departments(args, role=role)
    return _run_single_department(args, role=role, caller_department=caller_department)


def _run_single_department(
    args: SqlArgs, *, role: str, caller_department: str
) -> tuple[str, list[dict]]:
    assert args.department is not None  # đảm bảo bởi schema.py cho query_type này
    if not can_query_department(
        role=role, caller_department=caller_department, target_department=args.department
    ):
        raise ToolPermissionError(
            f"role='{role}' department='{caller_department}' không được xem doanh thu "
            f"của phòng '{args.department}'"
        )

    rows = fetch_all(
        _SQL_SINGLE_DEPARTMENT,
        {
            "department": args.department,
            "month_from": args.month_from,
            "month_to": args.month_to,
        },
    )
    if not rows:
        raise ToolExecutionError(
            f"Không có số liệu doanh thu cho {args.department} từ {args.month_from} "
            f"đến {args.month_to}"
        )

    return "\n".join(_format_revenue_line(r) for r in rows), rows


def _run_compare_departments(args: SqlArgs, *, role: str) -> tuple[str, list[dict]]:
    if not can_compare_departments(role=role):
        raise ToolPermissionError(
            f"role='{role}' không được so sánh doanh thu liên phòng ban — chỉ executive"
        )

    rows = fetch_all(
        _SQL_COMPARE_DEPARTMENTS,
        {"month_from": args.month_from, "month_to": args.month_to},
    )
    if not rows:
        raise ToolExecutionError(
            f"Không có số liệu doanh thu nào từ {args.month_from} đến {args.month_to}"
        )

    lines = [f"{r['full_name']} ({r['department']}): {_format_revenue_line(r)}" for r in rows]
    return "\n".join(lines), rows


def _format_revenue_line(row: dict) -> str:
    """Định dạng một dòng doanh thu, kèm tăng trưởng so tháng trước nếu có — cột
    `mom_growth_pct` đã được cả hai câu SQL tính sẵn bằng window function, trước đây
    bị bỏ phí vì không hiện ra trong câu trả lời."""
    tentative = " (tạm tính)" if not row["is_final"] else ""
    line = f"{row['month']:%Y-%m}: {row['revenue_vnd']:,} VND{tentative}"
    growth = row.get("mom_growth_pct")
    if growth is not None:
        sign = "+" if growth >= 0 else ""
        line += f" ({sign}{growth}% so tháng trước)"
    return line


# 3. Công Cụ Truy Vấn Tài Liệu Quy Trình (docs_tool)


def docs_tool(query: str, *, role: str, k: int = 5) -> list[RetrievedChunk]:
    """Tìm kiếm ngữ nghĩa các đoạn tài liệu quy trình; phân quyền RBAC được áp ở retrieve()."""
    return retrieve(query, role=role, k=k)


# 4. Danh Sách Ngoại Lệ Mạng Có Thể Thử Lại (Retryable Errors)

# Gom các lỗi mạng tạm thời thành alias dùng chung để loop.py không bị phụ thuộc vào httpx.
RETRYABLE_NETWORK_ERRORS = (httpx.ConnectError, httpx.TimeoutException)
