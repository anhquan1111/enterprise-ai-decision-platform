"""Trich xuat van ban tu anh/PDF bang Gemini vision (multimodal), khong dung OCR
engine cuc bo. Ly do chon huong nay va rui ro cua no: xem vault
D:/Documents/AI/Update/OCR_Ingestion/1. OCR_Co_Che_Va_Phuong_Phap.md.

CHI dung o buoc ingest. Duong tra loi cau hoi (/ask, src/agent/) khong bao gio import
module nay — mot khi van ban da nam trong doc_chunks, agent khong biet va khong can
biet chunk do tung la anh scan hay khong.
"""

import base64
import random
import time

import httpx

from src.config import get_settings

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_NETWORK_RETRY_ATTEMPTS = 3
_NETWORK_RETRY_BACKOFF_S = 1.0
# D4: xem giải thích đầy đủ ở generation.py — jitter chống nhiều request đồng thời
# retry cùng lịch, đo thật ở ngày 25 (vault).
_NETWORK_RETRY_JITTER_S = 0.5

GENERATE_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
REQUEST_TIMEOUT = 60.0  # tai liệu nhieu trang cham hon mot lenh goi text thuan

SUPPORTED_MIME_TYPES = frozenset({"application/pdf", "image/png", "image/jpeg"})

EXTRACTION_PROMPT = (
    "Trich xuat NGUYEN VAN toan bo van ban co trong tai lieu nay, giu dung thu tu "
    "xuat hien. KHONG dien giai, KHONG tom tat, KHONG them bat ky chu nao khong co "
    "trong tai lieu goc. Neu co bang, trinh bay lai duoi dang van ban co cau truc ro "
    "rang (moi hang mot dong). Neu mot doan khong doc ro, ghi [khong doc duoc] o "
    "dung vi tri do thay vi doan bua mot noi dung hop ly."
)


class OcrError(Exception):
    """Gemini không trả được văn bản — hết lượt retry mạng, hoặc response rỗng."""


def extract_text(file_bytes: bytes, *, mime_type: str) -> str:
    """Gọi Gemini vision một lần, trả về văn bản trích xuất.

    Args:
        file_bytes: Nội dung nhị phân thật của file (không phải đường dẫn).
        mime_type: Một trong ``SUPPORTED_MIME_TYPES``. Sai giá trị này là lỗi lập
            trình (gọi sai), không phải lỗi mạng — nên raise ngay, không retry.
    """
    if mime_type not in SUPPORTED_MIME_TYPES:
        raise ValueError(
            f"mime_type không hỗ trợ: {mime_type!r}. Hỗ trợ: {sorted(SUPPORTED_MIME_TYPES)}"
        )

    settings = get_settings()
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "inlineData": {
                            "mimeType": mime_type,
                            "data": base64.b64encode(file_bytes).decode("ascii"),
                        }
                    },
                    {"text": EXTRACTION_PROMPT},
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": settings.llm_max_output_tokens,
        },
    }

    last_exc: httpx.HTTPStatusError | None = None
    response: httpx.Response | None = None
    for attempt in range(_NETWORK_RETRY_ATTEMPTS):
        response = httpx.post(
            GENERATE_URL.format(model=settings.llm_model),
            headers={"x-goog-api-key": settings.llm_api_key, "Content-Type": "application/json"},
            timeout=REQUEST_TIMEOUT,
            json=payload,
        )
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
    finish_reason = candidate.get("finishReason")
    text = "".join(p.get("text", "") for p in candidate.get("content", {}).get("parts", []))
    if not text.strip():
        raise OcrError(f"Gemini trả về văn bản rỗng (finishReason={finish_reason})")
    return text
