"""Hai tool cua agent giai doan agent routing: sql (so lieu doanh thu) va docs
(chinh sach/quy trinh).

Ca hai tool deu ap dung dung nguyen tac da hoc o Ngay 22: RBAC kiem TRUOC khi thuc
thi, khong phai loc sau; loi ha tang (mang, timeout) khac loi nghiep vu (khong co du
lieu, sai tham so) va xu ly khac nhau.
"""

from pathlib import Path

import httpx

from src.db import fetch_all
from src.retrieval import RetrievedChunk, retrieve
from src.scope import can_query_department

from .schema import SqlArgs

_SQL_QUERY = (Path(__file__).parent.parent.parent / "sql" / "03_business_metrics.sql").read_text(
    encoding="utf-8"
)


class ToolPermissionError(Exception):
    """RBAC chặn — role/department của người gọi không được phép thấy dữ liệu này.

    Tách khỏi ToolExecutionError: đây không phải "không có dữ liệu", mà là "có dữ
    liệu nhưng người gọi không được xem" — hai lý do abstain khác nhau, xem 8 nhãn
    lỗi của giai đoạn retrieval nền tảng (access_correct khác no_knowledge_correct).
    """


class ToolExecutionError(Exception):
    """Lỗi nghiệp vụ: tham số hợp lệ nhưng không có dữ liệu khớp. KHÔNG retry — thử
    lại với đúng tham số đó chắc chắn ra đúng lỗi đó lần nữa."""


def sql_tool(args: SqlArgs, *, role: str, caller_department: str) -> tuple[str, list[dict]]:
    """Trả về (câu trả lời dạng văn bản, các dòng thô để trích dẫn).

    RBAC kiểm TRƯỚC khi câu SQL chạy — một role/department không đủ quyền không bao
    giờ khiến database chạy câu truy vấn, không chỉ là kết quả bị giấu đi sau đó.
    """
    if not can_query_department(
        role=role, caller_department=caller_department, target_department=args.department
    ):
        raise ToolPermissionError(
            f"role='{role}' department='{caller_department}' không được xem doanh thu "
            f"của phòng '{args.department}'"
        )

    rows = fetch_all(
        _SQL_QUERY,
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

    lines = [
        f"{r['month']:%Y-%m}: {r['revenue_vnd']:,} VND{' (tạm tính)' if not r['is_final'] else ''}"
        for r in rows
    ]
    return "\n".join(lines), rows


def docs_tool(query: str, *, role: str, k: int = 5) -> list[RetrievedChunk]:
    """RBAC (access_level theo role) đã áp trong ``retrieve()`` — xem ADR-009."""
    return retrieve(query, role=role, k=k)


# Lỗi mạng thoáng qua (Gemini/PostgreSQL tạm không tới được) đáng retry ở tầng loop;
# gom vào một alias để loop.py không phải biết chi tiết httpx bên trong tools.py.
RETRYABLE_NETWORK_ERRORS = (httpx.ConnectError, httpx.TimeoutException)
