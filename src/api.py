"""Điểm vào FastAPI: định tuyến câu hỏi, xác thực danh tính, kiểm toán và giám sát."""

import logging
import time
import uuid
from typing import Literal

import httpx
from fastapi import FastAPI, Header, status
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from src.agent.loop import AgentAnswer, run_agent
from src.audit import AuditEntry
from src.audit import record as record_audit
from src.auth import AuthenticationError, authenticate
from src.config import get_settings
from src.db import check_connection
from src.generation import SchemaFailure
from src.identity import AuthenticatedEmployee
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

# ==============================================================================
# 1. Khởi tạo ứng dụng FastAPI & Cấu hình giám sát
# ==============================================================================

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


# ==============================================================================
# 2. Endpoint kiểm tra sức khỏe hệ thống (/health, /ready, /metrics)
# ==============================================================================


@app.get("/health", response_model=HealthResponse, tags=["ops"])
def health() -> HealthResponse:
    """Liveness probe: Xác nhận tiến trình API đang chạy, không kiểm tra CSDL phụ thuộc."""
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
    )


@app.get("/ready", response_model=ReadyResponse, tags=["ops"])
def ready() -> JSONResponse:
    """Readiness probe: Kiểm tra kết nối tới CSDL PostgreSQL phục vụ request."""
    checks: dict[str, str] = {}
    try:
        version = check_connection()
        checks["postgres"] = f"ok ({version.split(',')[0]})"
        is_ready = True
    except Exception as exc:  # noqa: BLE001 - Báo lỗi ra caller, không nuốt lỗi
        checks["postgres"] = f"unreachable: {type(exc).__name__}"
        is_ready = False

    payload = ReadyResponse(ready=is_ready, checks=checks)
    code = status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=code, content=payload.model_dump())


@app.get("/metrics", tags=["ops"])
def metrics() -> Response:
    """Endpoint thu thập số liệu Prometheus: Xuất các metric đo lường hiệu năng và lỗi."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ==============================================================================
# 3. Endpoint cấp phát vé thông hành JWT (/auth/token)
# ==============================================================================


@app.post("/auth/token", response_model=TokenResponse, tags=["auth"])
def issue_jwt(authorization: str | None = Header(default=None)) -> JSONResponse:
    """Đổi API key dài hạn lấy token JWT ngắn hạn có thời hạn (mặc định 60 phút).

    Giúp ứng dụng web xác thực nhanh trong RAM mà không cần truy vấn CSDL liên tục.
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


# Ba danh tính demo CỐ ĐỊNH, chỉ đọc dữ liệu tổng hợp — dùng riêng cho /auth/demo-token
# (trang /ui công khai) để một người xem trang không cần có API key thật vẫn tự bấm
# thử được. Không phải nhân viên thật, không có API key nào đứng sau (bỏ qua hẳn bước
# xác thực credential) — xem ADR-029/031 vì sao KHÔNG hardcode API key thật vào
# frontend, dùng cách này thay thế.
_DEMO_ACCOUNTS: dict[str, AuthenticatedEmployee] = {
    "employee": AuthenticatedEmployee(
        employee_id="demo_ui_frontend", role="employee", department="sales"
    ),
    "manager": AuthenticatedEmployee(
        employee_id="demo_ui_manager", role="manager", department="finance"
    ),
    "executive": AuthenticatedEmployee(
        employee_id="demo_ui_exec", role="executive", department="finance"
    ),
}


@app.post("/auth/demo-token", response_model=TokenResponse, tags=["auth"])
def issue_demo_jwt(role: Literal["employee", "manager", "executive"]) -> JSONResponse:
    """Cấp JWT cho một trong ba danh tính demo cố định — KHÔNG kiểm bất kỳ credential
    nào, chỉ để trang `/ui` công khai tự phục vụ (nhà tuyển dụng/người đọc repo bấm
    thử ngay, không cần chạy `scripts/issue_api_keys.py`).

    Không bao giờ dùng mô hình này cho danh tính nhân viên thật — endpoint này tồn
    tại đúng vì ba danh tính ở trên không đứng sau bất kỳ dữ liệu thật hay quyền ghi
    nào, không phải vì "bỏ xác thực" là chấp nhận được nói chung.
    """
    employee = _DEMO_ACCOUNTS[role]
    token = issue_token(employee)
    response = TokenResponse(access_token=token, expires_in=settings.jwt_expiry_minutes * 60)
    return JSONResponse(status_code=status.HTTP_200_OK, content=response.model_dump())


# ==============================================================================
# 4. Hàm tiện ích chuyển đổi dữ liệu trích dẫn & ánh xạ công cụ
# ==============================================================================


def _to_response_citations(result: AgentAnswer) -> list[Citation]:
    """Chuyển đổi trích dẫn từ kết quả agent sang định dạng hợp đồng phản hồi API."""
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


# ==============================================================================
# 5. Điểm vào chính xử lý câu hỏi & ghi vết kiểm toán (/ask)
# ==============================================================================


@app.post("/ask", response_model=AskResponse, tags=["qa"])
def ask(request: AskRequest, authorization: str | None = Header(default=None)) -> JSONResponse:
    """Tiếp nhận câu hỏi, xác thực danh tính, điều phối agent và lưu audit log.

    Quy trình bảo mật & vận hành:
    1. Xác thực danh tính người gọi qua Header Authorization (JWT hoặc API Key).
    2. Đối chiếu Zero-Trust: Khóa chặt nếu role/department tự khai báo sai với token.
    3. Thực thi Agent pipeline: Truy vấn số liệu SQL và tài liệu quy trình.
    4. Ghi nhận thời gian, token tiêu thụ, lỗi grounding và vết kiểm toán vào audit_log.
    """
    request_id = str(uuid.uuid4())
    started = time.perf_counter()

    # Bước 1: Xác thực danh tính người gọi
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

    # Bước 2: Kiểm soát Zero-Trust - Ngăn chặn mạo danh vai trò hoặc phòng ban
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

    # Bước 3: Chạy pipeline Agent dựa trên danh tính đã xác thực (Nguồn chân lý duy nhất)
    try:
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

    # Bước 4: Lưu nhật ký kiểm toán vĩnh viễn (Audit Log) phục vụ kế toán & FinOps
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

    # Bước 5: Đóng gói phản hồi API
    response = AskResponse(
        request_id=request_id,
        answer=result.answer,
        citations=response_citations,
        tool_used=_TOOL_USED_MAP[result.tool_used],
        abstained=result.abstained,
        latency_ms=elapsed_ms,
    )
    return JSONResponse(status_code=status.HTTP_200_OK, content=response.model_dump())


# ==============================================================================
# 6. Giao diện demo tĩnh (/ui) — chỉ để quay video/GIF, không phải sản phẩm
# ==============================================================================
# Mount SAU cùng, và ở một tiền tố riêng (/ui) — không phải "/" — để không bao giờ
# che khuất một route API nào phía trên nếu path trùng nhau. HTML/CSS/JS thuần, không
# build step, không framework: nhất quán với nguyên tắc "không thêm hạ tầng khi không
# cần" đã áp dụng xuyên suốt dự án.
app.mount("/ui", StaticFiles(directory="web", html=True), name="ui")
