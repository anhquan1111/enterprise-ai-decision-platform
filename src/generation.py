"""Sinh câu trả lời có cấu trúc từ các chunk văn bản qua hai cổng kiểm duyệt độc lập.

Cổng 1 xác thực JSON Schema Pydantic; Cổng 2 kiểm tra tính căn cứ (Grounding) & trích dẫn.
"""

import json
import random
import time
from dataclasses import dataclass

import httpx
from pydantic import BaseModel, Field, ValidationError, model_validator

from src.config import get_settings
from src.retrieval import RetrievedChunk

# 1. Cấu hình & Tham số Thử Lại Mạng (Retry & Jitter)

# 429 (rate limit) và 5xx (lỗi server) mang tính tạm thời nên retry có tác dụng khắc phục.
# Các mã 4xx khác (400, 401, 403) là lỗi logic cố định, retry sẽ chỉ tốn thêm tiền vô ích.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_NETWORK_RETRY_ATTEMPTS = 3
_NETWORK_RETRY_BACKOFF_S = 1.0

# Jitter ngẫu nhiên làm lệch pha các request đồng thời, tránh hiện tượng thundering herd
# khiến nhiều worker cùng retry vào một thời điểm và va lại vào ngưỡng rate limit 503.
_NETWORK_RETRY_JITTER_S = 0.5

# Timeout hoặc rớt socket ở tầng mạng không trả HTTP status code nên cần bắt riêng qua exception
# để tiếp tục vòng retry, tránh việc hệ thống lập tức sập 503 khi mạng chập chờn (ADR-020).
_NETWORK_LEVEL_RETRYABLE = (httpx.ConnectError, httpx.TimeoutException)

GENERATE_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
REQUEST_TIMEOUT = 60.0

# Chỉ thị hệ thống ép LLM chỉ trả về duy nhất một đối tượng JSON và bắt buộc trích dẫn nguyên văn.
# Tuyệt đối không sinh thêm bất kỳ lời dẫn hay văn bản giải thích nào ngoài định dạng JSON.
SYSTEM_INSTRUCTION = (
    "Bạn là trợ lý nội bộ của công ty. Chỉ trả lời dựa trên các đoạn tài liệu được "
    "cung cấp dưới đây, không dùng kiến thức ngoài. Mọi khẳng định phải kèm chunk_id "
    "làm nguồn, trích dẫn nguyên văn từ đoạn tương ứng. Nếu các đoạn không chứa đáp "
    "án cho câu hỏi, trả về abstained=true, answer giải thích ngắn gọn, và citations "
    'rỗng. Chỉ trả về ĐÚNG MỘT JSON object dạng: {"answer": "...", "citations": '
    '[{"chunk_id": "...", "quote": "..."}], "abstained": false}'
)


# 2. Khế Ước Dữ Liệu & Mô Hình Pydantic (Data Contract)


class Citation(BaseModel):
    """Trích dẫn căn cứ gồm mã định danh đoạn văn bản và câu văn nguyên văn tương ứng."""

    chunk_id: str = Field(min_length=1)
    quote: str = Field(min_length=1)


class Answer(BaseModel):
    """Mô hình dữ liệu câu trả lời của AI kèm danh sách trích dẫn và cờ từ chối."""

    answer: str = Field(min_length=1)
    citations: list[Citation]
    abstained: bool
    # Đánh dấu True nếu model tự mâu thuẫn (vừa từ chối vừa gửi citation) và đã được tự động sửa.
    self_contradiction_corrected: bool = False

    @model_validator(mode="after")
    def normalize_abstain_citations(self) -> "Answer":
        """Xử lý mâu thuẫn nội tại: model trả abstained=true nhưng vẫn đính kèm citations sót lại.

        Thay vì raise SchemaFailure làm sập toàn bộ request với lỗi 502, ta ưu tiên tín hiệu an toàn
        abstained=true, tự động dọn sạch citations thừa và ghi nhận cờ để Cổng 2 kiểm tra (ADR-019).
        """
        if self.abstained and self.citations:
            self.citations = []
            self.self_contradiction_corrected = True
        return self


class SchemaFailure(Exception):
    """Ngoại lệ khi phản hồi của LLM không khớp với cấu trúc JSON mong đợi sau số lần thử lại."""


@dataclass
class GroundedAnswer:
    """Kết quả hoàn chỉnh sau khi đi qua Cổng Schema (cấu trúc) và Cổng Grounding (bằng chứng)."""

    answer: Answer
    grounding_problems: list[str]
    attempts: int
    total_tokens: int = 0


# 3. Xây Dựng Prompt & Chuẩn Hóa Chuỗi JSON (Prompt Engineering)


def build_prompt(question: str, chunks: list[RetrievedChunk]) -> str:
    """Ghép ngữ cảnh các đoạn tài liệu kèm chunk_id và câu hỏi người dùng thành prompt."""
    if not chunks:
        # Chặn đứng trường hợp danh sách chunk rỗng ngay từ đầu để tránh model tự suy diễn bịa đặt.
        raise ValueError("build_prompt không được gọi với danh sách chunk rỗng")
    lines = [f"[{c.chunk_id}] {c.chunk_text}" for c in chunks]
    return "Cac doan tai lieu:\n" + "\n".join(lines) + f"\n\nCau hoi: {question}"


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


# 4. Giao Tiếp LLM Gemini API Kèm Retry & Jitter


def _call_gemini(prompt: str) -> tuple[str, str | None, int]:
    """Gọi API sinh nội dung của Gemini với cơ chế Exponential Backoff + Jitter và hard timeout.

    Returns:
        tuple gồm (văn bản thô, lý do kết thúc finish_reason, tổng số token sử dụng).
        Lý do kết thúc cần kiểm tra riêng vì thinking token có thể nuốt hết trần max_tokens.
    """
    settings = get_settings()
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.1,
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
            # Bắt lỗi rớt mạng hoặc timeout tầng socket để tiếp tục thử lại thay vì crash ngay.
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

    # Ví dụ JSON Gemini trả về:
    # body = {"candidates": [{"content": {"parts": [{"text": "abc"}]}}]}
    #
    # 1. body["candidates"][0] -> {"content": {"parts": [{"text": "abc"}]}}
    candidate = body["candidates"][0]

    # 2. candidate.get("content", {}) -> {"parts": [{"text": "abc"}]}
    # 3. .get("parts", [])            -> [{"text": "abc"}]
    parts = candidate.get("content", {}).get("parts", [])

    # 4. p.get("text", "") lấy "abc", join lại thành chuỗi hoàn chỉnh text = "abc"
    text = "".join(p.get("text", "") for p in parts)
    total_tokens = body.get("usageMetadata", {}).get("totalTokenCount", 0)
    return text, candidate.get("finishReason"), total_tokens


# 5. Hai Cổng Kiểm Duyệt Độc Lập (Schema Gate & Grounding Gate)


def _parse_and_validate(raw: str, *, finish_reason: str | None) -> Answer:
    """Cổng 1 (Schema Gate): Xác thực chuỗi JSON thô khớp chính xác với cấu trúc Pydantic."""
    if not raw.strip():
        raise SchemaFailure(f"response rỗng (finishReason={finish_reason})")
    try:
        payload = json.loads(_extract_json(raw))
    except json.JSONDecodeError as exc:
        raise SchemaFailure(f"không phải JSON hợp lệ: {exc.msg}") from exc
    try:
        return Answer.model_validate(payload)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        raise SchemaFailure(f"sai schema: {problems}") from exc


def check_grounding(answer: Answer, allowed_chunk_ids: set[str]) -> list[str]:
    """Cổng 2 (Grounding Gate): Kiểm tra tính căn cứ và nguồn gốc của các trích dẫn tài liệu.

    Đảm bảo mọi chunk_id được trích dẫn đều nằm trong tập ngữ cảnh ban đầu đưa cho model.
    """
    problems: list[str] = []
    if answer.self_contradiction_corrected:
        problems.append(
            "model trả abstained=true kèm citations — đã tự động bỏ citations, giữ "
            "abstained (giai đoạn báo cáo cuối)"
        )
    for c in answer.citations:
        if c.chunk_id not in allowed_chunk_ids:
            problems.append(f"citation trỏ tới chunk ngoài context: {c.chunk_id}")
        if not c.quote.strip():
            problems.append(f"quote rỗng cho {c.chunk_id}")
    if not answer.abstained and not answer.citations:
        problems.append("có câu trả lời nhưng không có citation nào")
    return problems


# 6. Bộ Điều Phối Sinh Câu Trả Lời (answer_question)


def answer_question(
    question: str, chunks: list[RetrievedChunk], *, max_attempts: int = 2
) -> GroundedAnswer:
    """Điều phối toàn bộ quy trình: nếu 0 chunk thì từ chối ngay, có chunk thì gọi LLM có tự sửa.

    Quy tắc fail-fast: không có chunk liên quan thì từ chối (abstained=True) ngay lập tức mà không
    gọi LLM, vừa tiết kiệm chi phí token vừa ngăn chặn hoàn toàn ảo giác (hallucination).
    """
    if not chunks:
        no_evidence = Answer(
            answer="Khong tim thay tai lieu lien quan trong pham vi quyen truy cap.",
            citations=[],
            abstained=True,
        )
        return GroundedAnswer(answer=no_evidence, grounding_problems=[], attempts=0, total_tokens=0)

    prompt = build_prompt(question, chunks)
    allowed_ids = {c.chunk_id for c in chunks}
    current_prompt = prompt
    last_error: str | None = None
    total_tokens = 0

    for attempt in range(1, max_attempts + 1):
        raw, finish_reason, tokens = _call_gemini(current_prompt)
        total_tokens += tokens
        try:
            parsed = _parse_and_validate(raw, finish_reason=finish_reason)
        except SchemaFailure as exc:
            last_error = str(exc)
            current_prompt = (
                f"{prompt}\n\nResponse trước không dùng được: {exc}\n"
                f"Trả lại CHỈ một JSON object đúng schema, không thêm lời dẫn."
            )
            continue
        problems = check_grounding(parsed, allowed_ids)
        return GroundedAnswer(
            answer=parsed, grounding_problems=problems, attempts=attempt, total_tokens=total_tokens
        )

    raise SchemaFailure(f"vẫn sai schema sau {max_attempts} lần: {last_error}")
