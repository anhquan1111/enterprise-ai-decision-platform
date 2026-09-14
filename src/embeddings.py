"""Gọi Gemini embedding API — một hàm duy nhất, dùng chung cho ingestion và truy vấn.

Một nguồn sự thật cho việc embed là điều kiện bắt buộc: nếu chunk được embed bằng một
cách chuẩn hóa và câu hỏi được embed bằng cách khác, hai vector nằm ở hai không gian
khác nhau — cosine similarity vẫn ra số, nhưng con số đó vô nghĩa. Đây đúng là rủi ro
train/serve skew đã nói ở Ngày 7 file 1 mục 5, áp cho embedding.
"""

from typing import Literal

import httpx

from src.config import get_settings

EMBED_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent"

# Timeout cho mỗi lần gọi. Không đặt thì theo đúng ADR-005: một request treo sẽ chờ vô
# hạn thay vì báo lỗi.
REQUEST_TIMEOUT = 30.0

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

    response = httpx.post(
        EMBED_URL.format(model=settings.embedding_model),
        headers={"x-goog-api-key": settings.llm_api_key, "Content-Type": "application/json"},
        timeout=REQUEST_TIMEOUT,
        json={
            "content": {"parts": [{"text": text}]},
            "taskType": task_type,
            "outputDimensionality": settings.embedding_dim,
        },
    )
    response.raise_for_status()
    values: list[float] = response.json()["embedding"]["values"]

    if len(values) != settings.embedding_dim:
        # Không im lặng chấp nhận: một vector sai số chiều sẽ bị PostgreSQL từ chối ở
        # ranh giới cột vector(384), nhưng báo lỗi ở đây sớm hơn và rõ ràng hơn.
        raise ValueError(
            f"Gemini trả về {len(values)} chiều, contract yêu cầu {settings.embedding_dim}"
        )
    return values
