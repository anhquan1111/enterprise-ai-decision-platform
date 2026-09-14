"""FastAPI application.

Phạm vi hiện tại (D2): /ask trả lời được câu hỏi tài liệu bằng dense retrieval +
structured output, có RBAC và abstention. Chưa có: tool SQL cho số liệu kinh doanh và
agent chọn giữa hai tool — đó là D3 (``agent routing`` theo docs/architecture.md).
/ask hôm nay luôn dùng tool DOCS; hỏi số liệu doanh thu sẽ bị coi là không có bằng
chứng và bị abstain, không phải bị trả lời sai.
"""

import logging
import time
import uuid

import httpx
from fastapi import FastAPI, status
from fastapi.responses import JSONResponse

from src.config import get_settings
from src.db import check_connection
from src.generation import GroundedAnswer, SchemaFailure, answer_question
from src.retrieval import retrieve
from src.schemas import AskRequest, AskResponse, Citation, HealthResponse, ReadyResponse, ToolUsed

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


def _to_response_citations(result: GroundedAnswer) -> list[Citation]:
    return [
        Citation(
            source_type=ToolUsed.DOCS,
            doc_id=c.chunk_id.split("#")[0],
            chunk_index=int(c.chunk_id.split("#")[1]),
            quote=c.quote,
        )
        for c in result.answer.citations
    ]


@app.post("/ask", response_model=AskResponse, tags=["qa"])
def ask(request: AskRequest) -> JSONResponse:
    """Trả lời câu hỏi tài liệu trong phạm vi quyền của người gọi.

    Luồng: retrieval (đã lọc quyền + thời điểm) -> generation có JSON mode -> hai
    cổng kiểm (schema, bằng chứng). Cổng bằng chứng không chặn response — nó được
    ghi lại để audit (D4), vì một câu trả lời có vấn đề grounding vẫn cần trả về cho
    người dùng kèm cảnh báo, không phải biến mất thành lỗi 500 im lặng.
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

    try:
        chunks = retrieve(request.question, role=request.role.value, k=settings.retrieval_top_k)
        result = answer_question(request.question, chunks)
    except SchemaFailure as exc:
        logger.error("request_id=%s generation gave up: %s", request_id, exc)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"request_id": request_id, "detail": str(exc), "latency_ms": elapsed_ms},
        )
    except httpx.HTTPError as exc:
        logger.error("request_id=%s upstream call failed: %s", request_id, exc)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
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

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    response = AskResponse(
        request_id=request_id,
        answer=result.answer.answer,
        citations=_to_response_citations(result),
        tool_used=ToolUsed.NONE if not chunks else ToolUsed.DOCS,
        abstained=result.answer.abstained,
        latency_ms=elapsed_ms,
    )
    return JSONResponse(status_code=status.HTTP_200_OK, content=response.model_dump())
