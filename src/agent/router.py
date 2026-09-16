"""Router phân loại ý đồ câu hỏi: gọi Gemini (JSON mode) để chọn công cụ phù hợp.

Áp dụng phân loại một lượt có cấu trúc: tách biệt retry mạng với retry schema, không fallback.
"""

import json
import random
import time
from dataclasses import dataclass

import httpx
from pydantic import ValidationError

from src.config import get_settings

from .schema import ToolPlan

# 1. Cấu Hình & Tham Số Thử Lại Mạng (Network Retry & Jitter)

# 429 (rate limit) và 5xx (lỗi server) mang tính tạm thời nên retry có tác dụng phục hồi.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_NETWORK_RETRY_ATTEMPTS = 3
_NETWORK_RETRY_BACKOFF_S = 1.0

# Jitter ngẫu nhiên làm lệch pha các request đồng thời, tránh hiện tượng thundering herd.
_NETWORK_RETRY_JITTER_S = 0.5

# Bắt riêng lỗi rớt mạng hoặc timeout tầng socket để tiếp tục thử lại (ADR-020).
_NETWORK_LEVEL_RETRYABLE = (httpx.ConnectError, httpx.TimeoutException)
_SCHEMA_RETRY_ATTEMPTS = 2

GENERATE_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
REQUEST_TIMEOUT = 30.0

SYSTEM_INSTRUCTION = """Bạn là router của một agent nội bộ công ty. Có 2 tool:
- "sql": tra số liệu doanh thu. Cần sql_args với hai loại query_type:
  * query_type="single_department" (mặc định, dùng khi câu hỏi hỏi về MỘT phòng
    ban cụ thể): cần thêm department (một trong "engineering","finance","hr","sales").
  * query_type="compare_departments" (dùng khi câu hỏi SO SÁNH nhiều phòng ban,
    hoặc hỏi doanh thu "các phòng ban"/"toàn công ty" chung chung): KHÔNG cần
    department.
  Cả hai đều cần month_from, month_to (định dạng YYYY-MM-01). Nếu câu hỏi không
  nêu rõ khoảng thời gian, dùng month_from="2000-01-01" và month_to="2100-01-01"
  để lấy toàn bộ dữ liệu hiện có.
- "docs": tra cứu chính sách/quy trình nội bộ bằng văn bản. Không cần tham số riêng.

Ví dụ câu hỏi so sánh liên phòng ban:
Câu hỏi: "So sanh doanh thu giua cac phong ban thang 1 nam 2026"
Trả lời đúng: {"tools": ["sql"], "sql_args": {"query_type": "compare_departments",
"month_from": "2026-01-01", "month_to": "2026-01-01"}}

QUAN TRỌNG - kiểm tra ĐỘC LẬP từng điều kiện sau, không chỉ chọn MỘT tool "nổi bật
nhất" trong câu hỏi:
1. Câu hỏi có hỏi một con số/số liệu kinh doanh cụ thể không (doanh thu, ...)?
   Nếu CÓ -> "sql" PHẢI có trong tools.
2. Câu hỏi có hỏi về chính sách/quy trình/quy định nội bộ không?
   Nếu CÓ -> "docs" PHẢI có trong tools.
Nếu CẢ HAI điều kiện đều đúng, tools PHẢI là ["sql","docs"] - không được chỉ chọn
một cái dù câu hỏi hỏi cả hai.

Ví dụ câu hỏi cần CẢ HAI tool:
Câu hỏi: "Doanh thu sales tháng 1 năm 2026 là bao nhiêu, và nhân viên kinh doanh
được tự quyết giảm giá tối đa bao nhiêu phần trăm?"
Trả lời đúng: {"tools": ["sql","docs"], "sql_args": {"department": "sales",
"month_from": "2026-01-01", "month_to": "2026-01-01"}}

Trả về CHỈ một JSON object đúng định dạng:
{"tools": ["sql"] hoặc ["docs"] hoặc ["sql","docs"],
 "sql_args": {...} hoặc bỏ qua nếu không dùng sql}
Không thêm chữ nào khác ngoài JSON."""


# 2. Ngoại Lệ & Đối Tượng Kết Quả Router (Custom Exceptions & Result)


class RouterSchemaFailure(Exception):
    """Router trả sai định dạng JSON ở mọi lần thử; không đoán mò mà dừng để loop xử lý.

    Mang theo total_tokens để tầng gọi hạch toán đầy đủ chi phí token của các lượt thử thất bại.
    """

    def __init__(self, message: str, total_tokens: int = 0) -> None:
        super().__init__(message)
        self.total_tokens = total_tokens


@dataclass(frozen=True)
class RouterResult:
    """Kết quả phân loại gồm ToolPlan và tổng số token thực tế đã sử dụng cho lần gọi router."""

    plan: ToolPlan
    total_tokens: int


# 3. Bóc Tách Chuỗi JSON Phòng Thủ (_extract_json)


def _extract_json(raw: str) -> str:
    """Bóc tách phần JSON thuần túy, loại bỏ các khối markdown code fence (```json ... ```)."""
    text = raw.strip()
    if "```" in text:
        start = text.find("```")
        fence = text[start + 3 :]
        if fence.lower().startswith("json"):
            fence = fence[4:]
        end = fence.find("```")
        text = (fence if end == -1 else fence[:end]).strip()
    first, last = text.find("{"), text.rfind("}")
    if first != -1 and last > first:
        text = text[first : last + 1]
    return text


# 4. Giao Tiếp LLM Gemini Để Phân Loại (_call_gemini)


def _call_gemini(prompt: str) -> tuple[str, int]:
    """Gọi Gemini phân loại với temperature=0.0 để đạt tính nhất quán tối đa và kèm retry."""
    settings = get_settings()
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.0,
            "maxOutputTokens": settings.llm_max_output_tokens,
        },
    }

    last_exc: Exception | None = None
    response: httpx.Response | None = None
    for attempt in range(_NETWORK_RETRY_ATTEMPTS):
        try:
            response = httpx.post(
                GENERATE_URL.format(model=settings.llm_model),
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
    body = response.json()
    candidate = body["candidates"][0]
    text = "".join(p.get("text", "") for p in candidate.get("content", {}).get("parts", []))
    total_tokens = body.get("usageMetadata", {}).get("totalTokenCount", 0)
    return text, total_tokens


# 5. Hàm Phân Loại Ý Đồ Câu Hỏi (route)


def route(question: str) -> RouterResult:
    """Quyết định tool cần gọi cho một câu hỏi dựa trên ý đồ, không phụ thuộc vào quyền hạn.

    Phân quyền RBAC được tách biệt hoàn toàn và chỉ áp dụng ở tầng thực thi (tools.py).
    """
    prompt = f"Cau hoi: {question}"
    last_error: str | None = None
    total_tokens = 0

    for _attempt in range(_SCHEMA_RETRY_ATTEMPTS):
        raw, tokens = _call_gemini(
            prompt
            if last_error is None
            else f"{prompt}\n\nLoi lan truoc: {last_error}\nTra lai DUNG dinh dang JSON."
        )
        total_tokens += tokens
        try:
            payload = json.loads(_extract_json(raw))
            return RouterResult(plan=ToolPlan.model_validate(payload), total_tokens=total_tokens)
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = str(exc)
            continue

    raise RouterSchemaFailure(
        f"router vẫn sai schema sau {_SCHEMA_RETRY_ATTEMPTS} lần: {last_error}",
        total_tokens=total_tokens,
    )
