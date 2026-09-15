"""Vong lap agent D3: router quyet dinh tool, RBAC kiem truoc thuc thi, thuc thi co
retry/timeout, roi tong hop cau tra loi cuoi.

Khac vong lap ReAct nhieu buoc day du (day hoc Ngay 22, Agent_Loop_&_Tool_Use): kien
truc /ask chi co dung 2 tool co dinh va MOT quyet dinh phan loai duy nhat (router.py),
khong can agent tu de xuat tung buoc — bien mot vong lap tong quat thanh mot pipeline
co dinh, gioi han (router -> RBAC -> thuc thi -> tong hop) van giu du nguyen cac
nguyen tac phong thu da hoc: RBAC kiem TRUOC thuc thi (khong phai loc sau — chinh day
la phong tuyen chong prompt injection, vi mot cau hoi hoac ket qua tool bi chen chi
thi gia van khong doi duoc bang RBAC tinh theo role/department), phan loai loi
ha-tang-thi-retry / nghiep-vu-thi-khong-retry, va khong bao gio bia cau tra loi khi
khong co bang chung nao.

Quyet dinh co chu y: KHONG dua so lieu SQL qua LLM de "dien dat lai". So lieu tra ve
tu database da la su thuc chinh xac; de LLM viet lai co nguy co dien sai/dien them —
mot rui ro hoan toan khong can thiet khi van ban that da co san. Phan docs (chinh
sach, can dien giai tu ngu canh) van di qua generation.answer_question() nhu D2.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

import httpx
import psycopg

from src.generation import Citation, GroundedAnswer, answer_question
from src.retrieval import RetrievedChunk

from .router import RouterResult, RouterSchemaFailure, route
from .schema import ToolPlan
from .tools import ToolExecutionError, ToolPermissionError, docs_tool, sql_tool

MAX_TOOL_RETRIES = 2

# Lỗi hạ tầng thoáng qua — đáng retry. ToolPermissionError/ToolExecutionError KHÔNG
# nằm trong danh sách này: retry một lỗi nghiệp vụ hoặc một lỗi quyền không tự sửa
# được gì, chỉ tốn thời gian và tiền gọi lại vô ích.
_RETRYABLE_EXCEPTIONS = (httpx.ConnectError, httpx.TimeoutException, psycopg.OperationalError)


@dataclass
class AgentAnswer:
    answer: str
    tool_used: str  # "sql" | "docs" | "both" | "none"
    abstained: bool
    doc_citations: list[Citation] = field(default_factory=list)
    sql_evidence: str | None = None
    sql_query: str | None = None
    blocked_reason: str | None = None
    grounding_problems: list[str] = field(default_factory=list)
    total_tokens: int = 0


def _retry[**P, T](fn: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
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


def run_agent(question: str, *, role: str, department: str, k: int = 5) -> AgentAnswer:
    """Điểm vào duy nhất của agent D3. Không bao giờ ném lỗi RBAC/nghiệp vụ ra ngoài —
    chúng được chuyển thành ``abstained=True`` có lý do rõ ràng. Lỗi hạ tầng (mạng,
    schema router hỏng sau khi hết retry) VẪN được ném ra để tầng API (``api.py``)
    trả đúng mã lỗi 502/503, giống hành vi đã có ở D2 cho generation.
    """
    try:
        router_result: RouterResult = route(question)
    except RouterSchemaFailure as exc:
        # Router không phân loại được câu hỏi ở mọi lần thử. Không đoán bừa tool nào
        # — coi như không có bằng chứng, giống hành vi 0-chunk đã có ở D2. Các lượt
        # gọi đã thử vẫn tốn tiền thật (D5) dù cuối cùng thất bại — exc.total_tokens
        # giữ lại con số đó thay vì báo 0 sai sự thật.
        return AgentAnswer(
            answer="Khong xac dinh duoc cau hoi nay can tra cuu so lieu hay tai lieu nao.",
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
            sql_query = (
                f"monthly_revenue WHERE department='{plan.sql_args.department}' "
                f"AND month BETWEEN '{plan.sql_args.month_from}' AND '{plan.sql_args.month_to}'"
            )
        except ToolPermissionError as exc:
            sql_blocked = str(exc)
        except ToolExecutionError:
            sql_evidence = None  # không có dữ liệu — không phải bị chặn, không báo lỗi

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


def _summarize(
    question: str,
    *,
    docs_chunks: list[RetrievedChunk],
    sql_evidence: str | None,
    sql_query: str | None,
    sql_blocked: str | None,
    router_tokens: int,
) -> AgentAnswer:
    docs_grounded: GroundedAnswer | None = None
    if docs_chunks:
        docs_grounded = answer_question(question, docs_chunks)  # có thể raise SchemaFailure

    # D5: chi phí token thật của MỘT request /ask = router + (docs generation nếu có
    # dùng). sql_tool không gọi LLM nên không cộng thêm gì.
    total_tokens = router_tokens + (docs_grounded.total_tokens if docs_grounded else 0)

    has_docs_answer = docs_grounded is not None and not docs_grounded.answer.abstained
    has_sql_answer = sql_evidence is not None

    if not has_docs_answer and not has_sql_answer:
        if sql_blocked:
            return AgentAnswer(
                answer="Ban khong co quyen xem so lieu duoc yeu cau.",
                tool_used="none",
                abstained=True,
                blocked_reason=sql_blocked,
                total_tokens=total_tokens,
            )
        fallback = (
            docs_grounded.answer.answer
            if docs_grounded
            else "Khong tim thay bang chung phu hop trong pham vi quyen truy cap."
        )
        return AgentAnswer(
            answer=fallback, tool_used="none", abstained=True, total_tokens=total_tokens
        )

    parts = []
    if has_sql_answer:
        parts.append(f"So lieu:\n{sql_evidence}")
    if has_docs_answer:
        assert docs_grounded is not None
        parts.append(f"Quy dinh:\n{docs_grounded.answer.answer}")

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
