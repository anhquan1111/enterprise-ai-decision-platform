"""Router: goi Gemini (JSON mode) de quyet dinh cau hoi can tool nao.

Ap dung dung mau da chot o generation.py — JSON mode, retry mang tach biet khoi retry
schema, khong fallback van xuoi. Day KHONG phai mot vong lap ReAct nhieu buoc: kien
truc /ask (docs/architecture.md) chi can MOT quyet dinh phan loai ("so lieu, quy tac,
hay ca hai"), khong can agent tu de xuat tung buoc mot nhu bai hoc Ngay 22 — o do vong
lap nhieu buoc can thiet vi khong biet truoc so tool se dung; o day kien truc da co
dung 2 tool co dinh, biet truoc hinh dang cau tra loi.
"""

import json
import random
import time
from dataclasses import dataclass

import httpx
from pydantic import ValidationError

from src.config import get_settings

from .schema import ToolPlan

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_NETWORK_RETRY_ATTEMPTS = 3
_NETWORK_RETRY_BACKOFF_S = 1.0
# D4: xem giải thích đầy đủ ở generation.py — đo thật ở ngày 25 (vault) cho thấy
# nhiều request đồng thời retry cùng lịch làm giảm hiệu quả phục hồi khi rate limit.
_NETWORK_RETRY_JITTER_S = 0.5
# D5 (ADR-020): timeout/mất kết nối không phải status code, không tự rơi vào nhánh
# retry ở dưới — xem giải thích đầy đủ ở generation.py (phát hiện qua held-out H02).
_NETWORK_LEVEL_RETRYABLE = (httpx.ConnectError, httpx.TimeoutException)
_SCHEMA_RETRY_ATTEMPTS = 2

GENERATE_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
REQUEST_TIMEOUT = 30.0

SYSTEM_INSTRUCTION = """Bạn là router của một agent nội bộ công ty. Có 2 tool:
- "sql": tra số liệu doanh thu theo phòng ban và tháng. Cần sql_args:
  department (một trong "engineering","finance","hr","sales"),
  month_from, month_to (định dạng YYYY-MM-01).
  Nếu câu hỏi không nêu rõ khoảng thời gian, dùng month_from="2000-01-01" và
  month_to="2100-01-01" để lấy toàn bộ dữ liệu hiện có.
- "docs": tra cứu chính sách/quy trình nội bộ bằng văn bản. Không cần tham số riêng.

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


class RouterSchemaFailure(Exception):
    """Router trả sai định dạng ở mọi lần thử — không đoán bừa nên tool nào, dừng rõ
    ràng để tầng gọi (agent loop) quyết định abstain, không phải fallback sang docs.

    Mang theo total_tokens (D5): các lượt gọi đã thử đều tốn tiền thật dù cuối cùng
    thất bại — tầng gọi cần con số này để hạch toán chi phí đúng, không chỉ tính
    token trên đường thành công.
    """

    def __init__(self, message: str, total_tokens: int = 0) -> None:
        super().__init__(message)
        self.total_tokens = total_tokens


@dataclass(frozen=True)
class RouterResult:
    """Bọc ToolPlan cùng chi phí token thật của lần gọi router (D5) — tách khỏi
    ToolPlan vì đó là schema phản ánh đúng hợp đồng JSON với Gemini, không phải chỗ
    để nhét thêm metadata đo lường."""

    plan: ToolPlan
    total_tokens: int


def _extract_json(raw: str) -> str:
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


def _call_gemini(prompt: str) -> tuple[str, int]:
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


def route(question: str) -> RouterResult:
    """Quyết định tool cần gọi cho một câu hỏi. Không biết role/department của người
    hỏi — router chỉ phân loại Ý ĐỊNH câu hỏi; RBAC áp riêng ở tầng thực thi tool
    (``tools.py``), không trộn hai quyết định vào một bước."""
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
