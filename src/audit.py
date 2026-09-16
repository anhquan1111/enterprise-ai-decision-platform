"""Module ghi nhận nhật ký kiểm toán (audit log) phục vụ giám sát và tuân thủ bảo mật."""

import logging
from dataclasses import dataclass
from uuid import UUID

from src.db import get_connection

logger = logging.getLogger(__name__)


# 1. Audit Entry Data Model
@dataclass(frozen=True)
class AuditEntry:
    """Mô hình dữ liệu một bản ghi kiểm toán sau khi xử lý xong câu hỏi của người dùng."""

    request_id: UUID
    user_id: str
    role: str
    department: str
    question: str
    tool_used: str
    retrieved_doc_ids: list[str]
    abstained: bool
    latency_ms: int
    llm_model: str | None = None
    total_tokens: int | None = None


# 2. Audit Record Dispatcher
def record(entry: AuditEntry) -> None:
    """Ghi nhận thông tin kiểm toán vào bảng audit_log theo cơ chế Fail-open.

    Triết lý thiết kế (ADR-017):
    - Ghi audit nhằm phục vụ quan sát, điều tra và tính cước, KHÔNG phải luồng xử lý chính.
    - Nếu Database audit bị nghẽn mạng hoặc lỗi, hàm chỉ ghi log cảnh báo ra console và
      TUYỆT ĐỐI KHÔNG quăng ngoại lệ làm sập request hay chặn người dùng nhận câu trả lời.
    - Bắt buộc truyền read_only=False vì mặc định get_connection() luôn khóa ghi (defense-in-depth).
    """
    try:
        with get_connection(read_only=False) as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audit_log (
                    request_id, user_id, role, department, question, tool_used,
                    retrieved_doc_ids, abstained, llm_model, total_tokens, latency_ms
                ) VALUES (
                    %(request_id)s, %(user_id)s, %(role)s, %(department)s, %(question)s,
                    %(tool_used)s, %(retrieved_doc_ids)s, %(abstained)s, %(llm_model)s,
                    %(total_tokens)s, %(latency_ms)s
                )
                """,
                {
                    "request_id": entry.request_id,
                    "user_id": entry.user_id,
                    "role": entry.role,
                    "department": entry.department,
                    "question": entry.question,
                    "tool_used": entry.tool_used,
                    "retrieved_doc_ids": entry.retrieved_doc_ids,
                    "abstained": entry.abstained,
                    "llm_model": entry.llm_model,
                    "total_tokens": entry.total_tokens,
                    "latency_ms": entry.latency_ms,
                },
            )
            conn.commit()
    except Exception:  # noqa: BLE001 - audit không được làm sập request, chỉ log
        logger.exception("audit_log ghi that bai cho request_id=%s", entry.request_id)
