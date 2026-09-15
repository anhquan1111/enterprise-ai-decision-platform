"""FastAPI application.

Phạm vi hiện tại (giai đoạn xác thực & độ tin cậy): /ask yêu cầu xác thực thật (API
key, `src/auth.py`) — role/department dùng cho RBAC lấy từ danh tính đã xác thực,
KHÔNG phải trường tự khai
trong body (lỗ hổng đã đo và ghi lại ở vault ngày 26, xem ADR về AuthN). Mỗi request
được ghi vào audit_log (`src/audit.py`) và đo bằng Prometheus (`src/metrics.py`,
`/metrics`). Router (Gemini JSON mode) quyết định tool SQL/docs, RBAC kiểm trước khi
bất kỳ tool nào chạy. Xem ``docs/decisions.md`` cho các quyết định không hiển nhiên.
"""

import logging
import time
import uuid

import httpx
from fastapi import FastAPI, Header, status
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from src.agent.loop import AgentAnswer, run_agent
from src.audit import AuditEntry
from src.audit import record as record_audit
from src.auth import AuthenticationError, authenticate
from src.config import get_settings
from src.db import check_connection
from src.generation import SchemaFailure
from src.jwt_auth import issue_token
from src.metrics import ask_auth_failures_total, ask_request_duration_seconds, ask_requests_total
from src.schemas import (
    AskRequest,
    AskResponse,
    Citation,
    HealthResponse,
    ReadyResponse,
    TokenResponse,
    ToolUsed,
)

settings = get_settings()
logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Enterprise AI Decision Platform",
    version=settings.app_version,
    description=(
        "Answers questions over internal business data (SQL) and policy documents "
        "(retrieval), with citations, role-based access control and an audit trail."
    ),
)


@app.get("/health", response_model=HealthResponse, tags=["ops"])
def health() -> HealthResponse:
    """Liveness: process đang chạy. Cố ý không gọi dependency nào."""
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
    )


@app.get("/ready", response_model=ReadyResponse, tags=["ops"])
def ready() -> JSONResponse:
    """Readiness: dependency cần để phục vụ request có tới được hay không."""
    checks: dict[str, str] = {}
    try:
        version = check_connection()
        checks["postgres"] = f"ok ({version.split(',')[0]})"
        is_ready = True
    except Exception as exc:  # noqa: BLE001 - báo ra cho caller, không nuốt lỗi
        checks["postgres"] = f"unreachable: {type(exc).__name__}"
        is_ready = False

    payload = ReadyResponse(ready=is_ready, checks=checks)
    code = status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=code, content=payload.model_dump())


@app.get("/metrics", tags=["ops"])
def metrics() -> Response:
    """Prometheus scrape endpoint (giai đoạn xác thực & độ tin cậy). Không cần xác
    thực — đúng quy ước Prometheus thông thường (bảo vệ bằng network
    policy/reverse proxy, không phải app-level auth)."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/auth/token", response_model=TokenResponse, tags=["auth"])
def issue_jwt(authorization: str | None = Header(default=None)) -> JSONResponse:
    """Đổi một API key hợp lệ lấy một JWT ngắn hạn (bước 2/3 của ADR-028).

    API key vẫn xác thực trực tiếp cho `/ask` y hệt trước — endpoint này KHÔNG thay
    thế đường đó, chỉ cấp thêm một lựa chọn. Dùng đúng `authenticate()` đã có (API
    key) để xác minh danh tính trước khi ký token — không thêm cơ chế xác thực thứ
    hai nào (không username/password, hệ thống này không có khái niệm đó); JWT ở
    đây là một dạng khác của cùng một danh tính đã được API key chứng minh, không
    phải một đường tin tưởng độc lập.
    """
    try:
        employee = authenticate(authorization)
    except AuthenticationError as exc:
        logger.warning("auth/token xac thuc that bai: %s", exc)
        ask_auth_failures_total.labels(reason="invalid_credentials").inc()
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "khong xac thuc duoc"},
        )

    token = issue_token(employee)
    response = TokenResponse(access_token=token, expires_in=settings.jwt_expiry_minutes * 60)
    return JSONResponse(status_code=status.HTTP_200_OK, content=response.model_dump())


def _to_response_citations(result: AgentAnswer) -> list[Citation]:
    doc_citations = [
        Citation(
            source_type=ToolUsed.DOCS,
            doc_id=c.chunk_id.split("#")[0],
            chunk_index=int(c.chunk_id.split("#")[1]),
            quote=c.quote,
        )
        for c in result.doc_citations
    ]
    if result.sql_query is not None:
        doc_citations.append(Citation(source_type=ToolUsed.SQL, sql=result.sql_query))
    return doc_citations


_TOOL_USED_MAP = {
    "sql": ToolUsed.SQL,
    "docs": ToolUsed.DOCS,
    "both": ToolUsed.BOTH,
    "none": ToolUsed.NONE,
}


@app.post("/ask", response_model=AskResponse, tags=["qa"])
def ask(request: AskRequest, authorization: str | None = Header(default=None)) -> JSONResponse:
    """Trả lời câu hỏi bằng agent 2 tool (giai đoạn agent routing), sau khi xác thực
    thật (giai đoạn xác thực & độ tin cậy).

    Thứ tự bắt buộc: xác thực (ai gọi đây, THẬT SỰ) → đối chiếu role/department
    request khớp với danh tính đã xác thực → agent (router chọn SQL/docs/cả hai,
    RBAC kiểm theo role/department ĐÃ XÁC THỰC, không phải trường tự khai) → audit.

    Cổng bằng chứng (grounding) của phần docs không chặn response — ghi lại để audit,
    vì một câu trả lời có vấn đề grounding vẫn cần trả về cho người dùng kèm cảnh
    báo, không phải biến mất thành lỗi 500 im lặng.
    """
    request_id = str(uuid.uuid4())
    started = time.perf_counter()

    try:
        employee = authenticate(authorization)
    except AuthenticationError as exc:
        logger.warning("request_id=%s xac thuc that bai: %s", request_id, exc)
        ask_auth_failures_total.labels(reason="invalid_credentials").inc()
        ask_requests_total.labels(tool_used="none", status="401").inc()
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"request_id": request_id, "detail": "khong xac thuc duoc"},
        )

    if employee.role != request.role.value or employee.department != request.department.value:
        logger.warning(
            "request_id=%s role/department trong body khong khop danh tinh da xac thuc "
            "(nhan vien=%s, body role=%s dept=%s)",
            request_id,
            employee.employee_id,
            request.role.value,
            request.department.value,
        )
        ask_auth_failures_total.labels(reason="role_mismatch").inc()
        ask_requests_total.labels(tool_used="none", status="403").inc()
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "request_id": request_id,
                "detail": "role/department trong request khong khop danh tinh da xac thuc",
            },
        )

    logger.info(
        "ask received request_id=%s user=%s role=%s dept=%s",
        request_id,
        employee.employee_id,
        employee.role,
        employee.department,
    )

    try:
        # Dùng role/department từ danh tính ĐÃ XÁC THỰC, không dùng trường request —
        # đây là nguồn sự thật duy nhất cho RBAC từ giai đoạn xác thực & độ tin cậy
        # trở đi (xem ADR về AuthN).
        result = run_agent(
            request.question,
            role=employee.role,
            department=employee.department,
            k=settings.retrieval_top_k,
        )
    except SchemaFailure as exc:
        logger.error("request_id=%s generation gave up: %s", request_id, exc)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        ask_requests_total.labels(tool_used="none", status="502").inc()
        ask_request_duration_seconds.labels(tool_used="none").observe(elapsed_ms / 1000)
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"request_id": request_id, "detail": str(exc), "latency_ms": elapsed_ms},
        )
    except httpx.HTTPError as exc:
        logger.error("request_id=%s upstream call failed: %s", request_id, exc)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        ask_requests_total.labels(tool_used="none", status="503").inc()
        ask_request_duration_seconds.labels(tool_used="none").observe(elapsed_ms / 1000)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "request_id": request_id,
                "detail": f"upstream error: {type(exc).__name__}",
                "latency_ms": elapsed_ms,
            },
        )

    if result.grounding_problems:
        logger.warning(
            "request_id=%s grounding problems: %s", request_id, result.grounding_problems
        )
    if result.blocked_reason:
        logger.info("request_id=%s blocked: %s", request_id, result.blocked_reason)

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    response_citations = _to_response_citations(result)

    ask_requests_total.labels(tool_used=result.tool_used, status="200").inc()
    ask_request_duration_seconds.labels(tool_used=result.tool_used).observe(elapsed_ms / 1000)

    record_audit(
        AuditEntry(
            request_id=uuid.UUID(request_id),
            user_id=employee.employee_id,
            role=employee.role,
            department=employee.department,
            question=request.question,
            tool_used=result.tool_used,
            retrieved_doc_ids=[c.chunk_id for c in result.doc_citations],
            abstained=result.abstained,
            latency_ms=elapsed_ms,
            llm_model=settings.llm_model,
            total_tokens=result.total_tokens,
        )
    )

    response = AskResponse(
        request_id=request_id,
        answer=result.answer,
        citations=response_citations,
        tool_used=_TOOL_USED_MAP[result.tool_used],
        abstained=result.abstained,
        latency_ms=elapsed_ms,
    )
    return JSONResponse(status_code=status.HTTP_200_OK, content=response.model_dump())
