"""Gọi Gemini embedding API — một hàm duy nhất, dùng chung cho ingestion và truy vấn.

Một nguồn sự thật cho việc embed là điều kiện bắt buộc: nếu chunk được embed bằng một
cách chuẩn hóa và câu hỏi được embed bằng cách khác, hai vector nằm ở hai không gian
khác nhau — cosine similarity vẫn ra số, nhưng con số đó vô nghĩa. Đây đúng là rủi ro
train/serve skew đã nói ở Ngày 7 file 1 mục 5, áp cho embedding.
"""

import random
import time
from typing import Literal

import httpx

from src.config import get_settings

EMBED_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent"

# Timeout cho mỗi lần gọi. Không đặt thì theo đúng ADR-005: một request treo sẽ chờ vô
# hạn thay vì báo lỗi.
REQUEST_TIMEOUT = 30.0

# Giai đoạn báo cáo cuối (ADR-024): retry/backoff/jitter y hệt generation.py và
# router.py — gap thật phát hiện khi chạy held-out v2: embeddings.py trước đây không
# hề retry, và agent/loop.py's _retry() chỉ bắt lỗi mạng (ConnectError/Timeout), không
# bắt HTTPStatusError, nên MỌI câu hỏi cần docs retrieval chỉ cần một lần 503 thoáng
# qua từ gemini-embedding-001 là chết hẳn, trong khi câu hỏi sql-only (không gọi
# embedding) vẫn qua bình thường cùng lúc đó — bất đối xứng độ tin cậy không có lý do
# chính đáng nào giữa hai đường LLM call.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_NETWORK_RETRY_ATTEMPTS = 3
_NETWORK_RETRY_BACKOFF_S = 1.0
_NETWORK_RETRY_JITTER_S = 0.5
_NETWORK_LEVEL_RETRYABLE = (httpx.ConnectError, httpx.TimeoutException)

TaskType = Literal["RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"]


def embed(text: str, *, task_type: TaskType) -> list[float]:
    """Trả về vector nhúng của một đoạn văn bản, đúng số chiều đã chốt ở ADR-002.

    Args:
        text: Văn bản cần embed — nội dung chunk lúc ingest, hoặc câu hỏi lúc truy vấn.
        task_type: Gemini tối ưu vector khác nhau tùy văn bản là tài liệu để lưu hay
            câu hỏi để tìm. Dùng sai loại không gây lỗi cú pháp, chỉ làm similarity
            kém chính xác hơn — một lớp lỗi âm thầm, giống hệt tinh thần ADR cũ.
    """
    settings = get_settings()
    if not settings.llm_api_key:
        raise RuntimeError("LLM_API_KEY rỗng — không thể gọi Gemini. Kiểm tra .env.")

    payload = {
        "content": {"parts": [{"text": text}]},
        "taskType": task_type,
        "outputDimensionality": settings.embedding_dim,
    }

    last_exc: Exception | None = None
    response: httpx.Response | None = None
    for attempt in range(_NETWORK_RETRY_ATTEMPTS):
        try:
            response = httpx.post(
                EMBED_URL.format(model=settings.embedding_model),
                headers={
                    "x-goog-api-key": settings.llm_api_key,
                    "Content-Type": "application/json",
                },
                timeout=REQUEST_TIMEOUT,
                json=payload,
            )
        except _NETWORK_LEVEL_RETRYABLE as exc:
            last_exc = exc
            response = None
        else:
            if response.status_code not in _RETRYABLE_STATUS:
                response.raise_for_status()
                break
            last_exc = httpx.HTTPStatusError(
                f"{response.status_code} tạm thời", request=response.request, response=response
            )
        if attempt < _NETWORK_RETRY_ATTEMPTS - 1:
            time.sleep(
                _NETWORK_RETRY_BACKOFF_S * (2**attempt) + random.uniform(0, _NETWORK_RETRY_JITTER_S)
            )
    else:
        assert last_exc is not None
        raise last_exc

    assert response is not None
    values: list[float] = response.json()["embedding"]["values"]

    if len(values) != settings.embedding_dim:
        # Không im lặng chấp nhận: một vector sai số chiều sẽ bị PostgreSQL từ chối ở
        # ranh giới cột vector(384), nhưng báo lỗi ở đây sớm hơn và rõ ràng hơn.
        raise ValueError(
            f"Gemini trả về {len(values)} chiều, contract yêu cầu {settings.embedding_dim}"
        )
    return values
