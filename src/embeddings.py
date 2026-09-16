"""Module gọi Gemini Embedding API phục vụ vector hóa tài liệu và câu hỏi tìm kiếm."""

import random
import time
from typing import Literal

import httpx

from src.config import get_settings

# 1. Constants & Network Resilience Configuration
EMBED_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent"

# Timeout cứng chống treo kết nối vô hạn theo ADR-005
REQUEST_TIMEOUT = 30.0

# Các mã lỗi HTTP tạm thời từ Gemini API cho phép thử lại (ADR-024)
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_NETWORK_RETRY_ATTEMPTS = 3
_NETWORK_RETRY_BACKOFF_S = 1.0
_NETWORK_RETRY_JITTER_S = 0.5
_NETWORK_LEVEL_RETRYABLE = (httpx.ConnectError, httpx.TimeoutException)

TaskType = Literal["RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"]


# 2. Embedding Client with Exponential Backoff & Jitter
def embed(text: str, *, task_type: TaskType) -> list[float]:
    """Tạo vector nhúng ngữ nghĩa của văn bản với số chiều thu gọn (Matryoshka 384D).

    Args:
        text: Nội dung văn bản (đoạn chunk khi nạp tài liệu hoặc câu hỏi khi truy vấn).
        task_type: Loại tác vụ nhúng:
            - RETRIEVAL_DOCUMENT: Tối ưu cho văn bản tài liệu lưu vào kho.
            - RETRIEVAL_QUERY: Tối ưu cho câu hỏi tìm kiếm của người dùng.
            Lưu ý: Dùng sai loại không báo lỗi cú pháp nhưng sẽ làm giảm độ chính xác tương đồng.

    Returns:
        Danh sách số thực biểu diễn vector 384 chiều chuẩn hóa.
    """
    settings = get_settings()
    if not settings.llm_api_key:
        raise RuntimeError("LLM_API_KEY rỗng — không thể gọi Gemini. Kiểm tra .env.")

    payload = {
        "content": {"parts": [{"text": text}]},
        "taskType": task_type,
        # Matryoshka 384D: Cắt gọn vector để tiết kiệm 50% RAM/Disk Postgres và tăng tốc truy vấn
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
            # Khi đứt mạng/timeout: lưu lỗi vào last_exc và cho phép đi tiếp để thử lại
            last_exc = exc
            response = None
        else:
            # Mạng thông: 200/4xx dừng ngay (break/raise); 429/503 tạm thời thì lưu để thử lại
            if response.status_code not in _RETRYABLE_STATUS:
                response.raise_for_status()
                break
            last_exc = httpx.HTTPStatusError(
                f"{response.status_code} tạm thời", request=response.request, response=response
            )

        if attempt < _NETWORK_RETRY_ATTEMPTS - 1:
            # Backoff + Jitter: ngủ 1s, 2s... kèm độ trễ ngẫu nhiên (0-0.5s) chống bão request
            time.sleep(
                _NETWORK_RETRY_BACKOFF_S * (2**attempt) + random.uniform(0, _NETWORK_RETRY_JITTER_S)
            )
    else:
        # Cú pháp for...else: chỉ chạy khi thử hết cả 3 lần đều thất bại (không gặp lệnh break)
        assert last_exc is not None
        raise last_exc

    assert response is not None
    # Trả về mảng số thực vector 384 chiều bóc tách từ JSON
    values: list[float] = response.json()["embedding"]["values"]

    if len(values) != settings.embedding_dim:
        raise ValueError(
            f"Gemini trả về {len(values)} chiều, contract yêu cầu {settings.embedding_dim}"
        )
    return values
