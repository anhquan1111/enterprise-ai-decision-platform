"""FastAPI application.

D0 scope: the service boots, reports liveness and readiness, and exposes the
/ask contract. /ask deliberately returns 501 until the retrieval and agent
layers land (D2-D3) — a stub that returned a plausible-looking answer would make
the endpoint look finished and would be the exact behaviour this project is
built to argue against.
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
    """Liveness: the process is running. Makes no dependency calls on purpose."""
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
    )


@app.get("/ready", response_model=ReadyResponse, tags=["ops"])
def ready() -> JSONResponse:
    """Readiness: dependencies needed to serve a request are reachable."""
    checks: dict[str, str] = {}
    try:
        version = check_connection()
        checks["postgres"] = f"ok ({version.split(',')[0]})"
        is_ready = True
    except Exception as exc:  # noqa: BLE001 - surfaced to the caller, not swallowed
        checks["postgres"] = f"unreachable: {type(exc).__name__}"
        is_ready = False

    payload = ReadyResponse(ready=is_ready, checks=checks)
    code = status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=code, content=payload.model_dump())


@app.post("/ask", tags=["qa"], status_code=status.HTTP_501_NOT_IMPLEMENTED)
def ask(request: AskRequest) -> JSONResponse:
    """Answer a question within the caller's access scope.

    Not implemented yet. The request contract is already enforced, so an invalid
    role or an empty question is rejected with 422 today.
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
