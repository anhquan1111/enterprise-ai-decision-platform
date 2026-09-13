"""FastAPI application.

Phạm vi hiện tại: service khởi động được, báo liveness/readiness, và áp contract cho
/ask. /ask vẫn trả 501 cho tới khi tầng retrieval và agent xong (D2-D3) — một stub
trả về câu trả lời trông như thật sẽ làm endpoint trông như đã hoàn thiện, và đó
đúng là hành vi project này được xây để phản đối.
"""

import logging
import time
import uuid

from fastapi import FastAPI, status
from fastapi.responses import JSONResponse

from src.config import get_settings
from src.db import check_connection
from src.schemas import AskRequest, HealthResponse, ReadyResponse

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


@app.post("/ask", tags=["qa"], status_code=status.HTTP_501_NOT_IMPLEMENTED)
def ask(request: AskRequest) -> JSONResponse:
    """Trả lời câu hỏi trong phạm vi quyền của người gọi.

    Chưa implement. Contract của request thì đã áp: role lạ hoặc câu hỏi rỗng bị
    chặn với 422 ngay từ hôm nay.
    """
    request_id = str(uuid.uuid4())
    started = time.perf_counter()
    logger.info(
        "ask received request_id=%s user=%s role=%s dept=%s",
        request_id,
        request.user_id,
        request.role,
        request.department,
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content={
            "request_id": request_id,
            "detail": "Not implemented yet: retrieval lands on D2, agent routing on D3.",
            "latency_ms": elapsed_ms,
        },
    )
