"""D4: ghi audit_log - bang da ton tai tu D1, chua tung duoc ghi vao cho toi bay gio.

Ghi audit KHONG duoc lam sap request cua nguoi dung: neu ghi log that bai (vd DB
tam thoi khong toi duoc), request van phai tra loi binh thuong - chi log loi ra
console. Day la lua chon co chu y, ghi lai ly do trong ADR: audit phuc vu tuan thu/
quan sat, khong phai duong di bat buoc de tra loi duoc cau hoi.
"""

import logging
from dataclasses import dataclass
from uuid import UUID

from src.db import get_connection

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuditEntry:
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


def record(entry: AuditEntry) -> None:
    """Ghi mot dong audit. Khong raise ra ngoai - loi ghi log chi duoc log lai, xem
    docstring module ve ly do."""
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
