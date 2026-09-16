"""Vòng lặp điều phối agent: định tuyến công cụ, kiểm soát RBAC, thực thi và tổng hợp."""

from collections.abc import Callable
from dataclasses import dataclass, field

import httpx
import psycopg

from src.generation import Citation, GroundedAnswer, answer_question
from src.retrieval import RetrievedChunk

from .router import RouterResult, RouterSchemaFailure, route
from .schema import SqlArgs, ToolPlan
from .tools import ToolExecutionError, ToolPermissionError, docs_tool, sql_tool

# ==============================================================================
# 1. Cấu hình thử lại hạ tầng & danh sách ngoại lệ mạng/DB
# ==============================================================================

MAX_TOOL_RETRIES = 2

# Chỉ thử lại các lỗi hạ tầng mạng/database mang tính thoáng qua (transient).
# Tuyệt đối KHÔNG retry ToolPermissionError hay ToolExecutionError: vi phạm quyền hoặc
# dữ liệu không tồn tại là lỗi xác thực/nghiệp vụ, retry chỉ gây nghẽn và tốn chi phí.
_RETRYABLE_EXCEPTIONS = (httpx.ConnectError, httpx.TimeoutException, psycopg.OperationalError)


# ==============================================================================
# 2. Cấu trúc kết quả điều phối agent (AgentAnswer)
# ==============================================================================


@dataclass
class AgentAnswer:
    """Kết quả phản hồi cuối cùng của agent sau khi tổng hợp các công cụ.

    Attributes:
        answer: Nội dung câu trả lời hoàn chỉnh trả về cho người dùng.
        tool_used: Loại công cụ đã sử dụng ("sql" | "docs" | "both" | "none").
        abstained: True nếu hệ thống từ chối trả lời do thiếu quyền hoặc thiếu dữ liệu.
        doc_citations: Danh sách trích dẫn nguồn chunk từ tài liệu nội bộ.
        sql_evidence: Dữ liệu bảng số liệu thực tế truy vấn từ cơ sở dữ liệu.
        sql_query: Mô tả câu truy vấn SQL an toàn đã được thực thi.
        blocked_reason: Lý do chi tiết nếu bị chặn bởi chính sách bảo mật RBAC/ABAC.
        grounding_problems: Danh sách phát hiện lỗi căn cứ (hallucination) từ Gate 2.
        total_tokens: Tổng số token tiêu thụ xuyên suốt vòng đời (Router + Docs).
    """

    answer: str
    tool_used: str  # "sql" | "docs" | "both" | "none"
    abstained: bool
    doc_citations: list[Citation] = field(default_factory=list)
    sql_evidence: str | None = None
    sql_query: str | None = None
    blocked_reason: str | None = None
    grounding_problems: list[str] = field(default_factory=list)
    total_tokens: int = 0


# ==============================================================================
# 3. Cơ chế thử lại hàm với ngoại lệ hạ tầng thoáng qua (_retry)
# ==============================================================================


def _retry[**P, T](fn: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    """Bọc lời gọi hàm với cơ chế thử lại lũy tiến khi gặp sự cố hạ tầng.

    Chỉ bắt các ngoại lệ trong _RETRYABLE_EXCEPTIONS. Bất kỳ ngoại lệ nghiệp vụ nào
    sẽ được ném thẳng ngay lập tức mà không retry.
    """
    last_exc: Exception | None = None
    for attempt in range(MAX_TOOL_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except _RETRYABLE_EXCEPTIONS as exc:
            last_exc = exc
            if attempt < MAX_TOOL_RETRIES:
                continue
            raise
    assert last_exc is not None
    raise last_exc


# ==============================================================================
# 4. Điểm vào thực thi & điều phối tiến trình agent (run_agent)
# ==============================================================================


def _describe_sql_query(args: SqlArgs) -> str:
    """Văn bản mô tả câu SQL đã chạy, dùng làm citation — KHÔNG phải câu SQL thật (đã
    tham số hoá, không nối chuỗi), chỉ để người dùng/audit biết agent đã tra gì."""
    if args.query_type == "compare_departments":
        return (
            f"monthly_revenue (mọi phòng ban) WHERE month BETWEEN "
            f"'{args.month_from}' AND '{args.month_to}'"
        )
    return (
        f"monthly_revenue WHERE department='{args.department}' "
        f"AND month BETWEEN '{args.month_from}' AND '{args.month_to}'"
    )


def run_agent(question: str, *, role: str, department: str, k: int = 5) -> AgentAnswer:
    """Điểm vào duy nhất của pipeline agent định tuyến và thực thi công cụ.

    Quy trình phối hợp:
    1. Định tuyến (Router): LLM phân tích câu hỏi -> chọn tool và tham số trích xuất.
    2. Kiểm soát RBAC & Thực thi:
       - SQL: Kiểm tra phòng ban và quyền hạn TRƯỚC KHI truy vấn DB.
       - Docs: Lọc vector theo cấp bậc quyền hạn (access_level).
    3. Phục hồi sự cố: Chuyển đổi lỗi quyền/nghiệp vụ thành abstained=True thay vì crash 500.

    Args:
        question: Câu hỏi ngôn ngữ tự nhiên từ người dùng.
        role: Vai trò đã xác thực của người gọi (employee, manager, executive).
        department: Phòng ban trực thuộc đã xác thực của người gọi.
        k: Số lượng chunk tài liệu tối đa cần thu thập cho Docs tool.

    Returns:
        AgentAnswer chứa câu trả lời, trích dẫn, bằng chứng SQL và tổng số token.
    """
    try:
        router_result: RouterResult = route(question)
    except RouterSchemaFailure as exc:
        # Khi router thất bại hoàn toàn sau các lượt thử, coi như không có căn cứ.
        # Vẫn ghi nhận exc.total_tokens để hạch toán chi phí API chính xác.
        return AgentAnswer(
            answer="Không xác định được câu hỏi này cần tra cứu số liệu hay tài liệu nào.",
            tool_used="none",
            abstained=True,
            blocked_reason="router_schema_failed",
            total_tokens=exc.total_tokens,
        )
    plan: ToolPlan = router_result.plan

    sql_evidence: str | None = None
    sql_query: str | None = None
    sql_blocked: str | None = None
    docs_chunks: list[RetrievedChunk] = []

    if "sql" in plan.tools:
        assert plan.sql_args is not None
        try:
            sql_evidence, _rows = _retry(
                sql_tool, plan.sql_args, role=role, caller_department=department
            )
            sql_query = _describe_sql_query(plan.sql_args)
        except ToolPermissionError as exc:
            # RBAC chặn truy vấn chéo phòng ban: ghi nhận lý do, không raise 500
            sql_blocked = str(exc)
        except ToolExecutionError:
            # Không tìm thấy số liệu trong CSDL: coi như không có dữ liệu số
            sql_evidence = None

    if "docs" in plan.tools:
        docs_chunks = _retry(docs_tool, question, role=role, k=k)

    return _summarize(
        question,
        docs_chunks=docs_chunks,
        sql_evidence=sql_evidence,
        sql_query=sql_query,
        sql_blocked=sql_blocked,
        router_tokens=router_result.total_tokens,
    )


# ==============================================================================
# 5. Tổng hợp kết quả đa công cụ & tính toán token (_summarize)
# ==============================================================================


def _summarize(
    question: str,
    *,
    docs_chunks: list[RetrievedChunk],
    sql_evidence: str | None,
    sql_query: str | None,
    sql_blocked: str | None,
    router_tokens: int,
) -> AgentAnswer:
    """Tổng hợp dữ liệu từ SQL và văn bản tài liệu thành câu trả lời thống nhất.

    Nguyên tắc vàng về độ chính xác số liệu:
    - Số liệu SQL từ DB được giữ NGUYÊN VĂN, tuyệt đối KHÔNG cho LLM diễn đạt lại
      nhằm triệt tiêu 100% rủi ro ảo giác tính toán sai lệch.
    - Văn bản chính sách tài liệu (docs) được tổng hợp qua generation.answer_question.
    - Token tiêu thụ = token router + token generation (SQL tool tốn 0 token).
    """
    docs_grounded: GroundedAnswer | None = None
    if docs_chunks:
        docs_grounded = answer_question(question, docs_chunks)

    # Chi phí token tổng hợp = router + generation (nếu có sử dụng Docs tool)
    total_tokens = router_tokens + (docs_grounded.total_tokens if docs_grounded else 0)

    has_docs_answer = docs_grounded is not None and not docs_grounded.answer.abstained
    has_sql_answer = sql_evidence is not None

    # Trường hợp không có dữ liệu từ cả hai nguồn
    if not has_docs_answer and not has_sql_answer:
        if sql_blocked:
            return AgentAnswer(
                answer="Bạn không có quyền xem số liệu được yêu cầu.",
                tool_used="none",
                abstained=True,
                blocked_reason=sql_blocked,
                total_tokens=total_tokens,
            )
        fallback = (
            docs_grounded.answer.answer
            if docs_grounded
            else "Không tìm thấy bằng chứng phù hợp trong phạm vi quyền truy cập."
        )
        return AgentAnswer(
            answer=fallback, tool_used="none", abstained=True, total_tokens=total_tokens
        )

    # Ghép câu trả lời từ các công cụ có kết quả
    parts = []
    if has_sql_answer:
        parts.append(f"Số liệu:\n{sql_evidence}")
    if has_docs_answer:
        assert docs_grounded is not None
        parts.append(f"Quy định:\n{docs_grounded.answer.answer}")

    tool_used = (
        "both" if (has_sql_answer and has_docs_answer) else ("sql" if has_sql_answer else "docs")
    )
    return AgentAnswer(
        answer="\n\n".join(parts),
        tool_used=tool_used,
        abstained=False,
        doc_citations=docs_grounded.answer.citations if (has_docs_answer and docs_grounded) else [],
        sql_evidence=sql_evidence,
        sql_query=sql_query if has_sql_answer else None,
        grounding_problems=docs_grounded.grounding_problems if docs_grounded else [],
        total_tokens=total_tokens,
    )
