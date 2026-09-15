"""Sinh câu trả lời có cấu trúc từ các chunk đã retrieval, và hai cổng kiểm.

Kiến trúc và các quyết định ở đây là áp dụng trực tiếp những gì đã học và đo ở
LLM_Inference_&_Structured_Output (ngày 19): JSON mode, thử lại có giới hạn kèm lỗi
cụ thể, không fallback văn xuôi, và hai cổng tách biệt — schema với bằng chứng.
"""

import json
import random
import time
from dataclasses import dataclass

import httpx
from pydantic import BaseModel, Field, ValidationError, model_validator

from src.config import get_settings
from src.retrieval import RetrievedChunk

# 429 (rate limit) và 5xx (lỗi phía server) là tạm thời — thử lại có ích. Mọi mã khác
# (400 sai request, 401/403 sai quyền) không tự sửa được bằng cách gọi lại, và thử
# lại một request hỏng chỉ tính tiền hai lần cho cùng một lỗi.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_NETWORK_RETRY_ATTEMPTS = 3
_NETWORK_RETRY_BACKOFF_S = 1.0
# Giai đoạn xác thực & độ tin cậy: jitter ngẫu nhiên cộng thêm vào backoff. Đo thật
# ở ngày 25 (vault): nhiều request đồng thời retry theo ĐÚNG cùng lịch (1s, 2s,
# 4s...) có xu hướng va lại rate limit ở cùng một thời điểm — 2/3 request đồng thời
# nhận 503 dù retry đã chạy. Jitter làm các request retry lệch pha nhau, giảm khả
# năng va lại.
_NETWORK_RETRY_JITTER_S = 0.5
# Giai đoạn báo cáo cuối (ADR-020): timeout/mất kết nối khi GỌI httpx.post không
# phải là một status code, nên trước đây thoát khỏi vòng retry ngay lập tức — phát
# hiện qua tập
# held-out (H02: "upstream call failed: The read operation timed out" -> 503
# không hề thử lại). Coi hai lớp lỗi này tương đương lỗi status tạm thời.
_NETWORK_LEVEL_RETRYABLE = (httpx.ConnectError, httpx.TimeoutException)

GENERATE_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
REQUEST_TIMEOUT = 60.0

SYSTEM_INSTRUCTION = (
    "Bạn là trợ lý nội bộ của công ty. Chỉ trả lời dựa trên các đoạn tài liệu được "
    "cung cấp dưới đây, không dùng kiến thức ngoài. Mọi khẳng định phải kèm chunk_id "
    "làm nguồn, trích dẫn nguyên văn từ đoạn tương ứng. Nếu các đoạn không chứa đáp "
    "án cho câu hỏi, trả về abstained=true, answer giải thích ngắn gọn, và citations "
    'rỗng. Chỉ trả về ĐÚNG MỘT JSON object dạng: {"answer": "...", "citations": '
    '[{"chunk_id": "...", "quote": "..."}], "abstained": false}'
)


class Citation(BaseModel):
    chunk_id: str = Field(min_length=1)
    quote: str = Field(min_length=1)


class Answer(BaseModel):
    answer: str = Field(min_length=1)
    citations: list[Citation]
    abstained: bool
    # Giai đoạn báo cáo cuối (ADR-020): True khi model tự mâu thuẫn (abstained=true
    # kèm citations) và
    # citations bị bỏ để giữ tín hiệu abstained — xem model_validator bên dưới.
    self_contradiction_corrected: bool = False

    @model_validator(mode="after")
    def normalize_abstain_citations(self) -> "Answer":
        """Model đôi khi trả abstained=true kèm citations còn sót — mâu thuẫn
        trong chính output của model, không phải lỗi hệ thống (phát hiện qua
        held-out H08, xem ADR-019). Trước đây raise ValueError ở đây khiến cả
        response bị coi là sai schema, retry rồi 502 — dù tín hiệu "từ chối trả
        lời" (abstained=true) là tín hiệu AN TOÀN, đáng tin hơn các citation thừa
        đi kèm. Giữ abstained=true, bỏ citations thừa, và ghi lại đã sửa (không
        âm thầm) để check_grounding() đưa vào grounding_problems."""
        if self.abstained and self.citations:
            self.citations = []
            self.self_contradiction_corrected = True
        return self


class SchemaFailure(Exception):
    """Response không qua được cổng schema sau khi đã thử lại."""


@dataclass
class GroundedAnswer:
    """Kết quả sau cả hai cổng: schema đạt, và biết rõ cổng bằng chứng có đạt không."""

    answer: Answer
    grounding_problems: list[str]
    attempts: int
    total_tokens: int = 0


def build_prompt(question: str, chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        # Không có chunk nào để đưa vào ngữ cảnh — không gọi model để nó tự bịa từ
        # kiến thức nền. Trạng thái "0 đoạn" phải được xử lý TRƯỚC khi tới đây, xem
        # answer_question(). Prompt này chỉ được build khi chunks không rỗng.
        raise ValueError("build_prompt không được gọi với danh sách chunk rỗng")
    lines = [f"[{c.chunk_id}] {c.chunk_text}" for c in chunks]
    return "Cac doan tai lieu:\n" + "\n".join(lines) + f"\n\nCau hoi: {question}"


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


def _call_gemini(prompt: str) -> tuple[str, str | None, int]:
    """Gọi Gemini, trả về (nội dung, finish_reason, total_tokens).

    finish_reason được trả riêng vì một response rỗng do thinking ăn hết
    max_output_tokens vẫn là HTTP 200 — phải đọc finish_reason mới biết, xem ADR-002.
    total_tokens (giai đoạn báo cáo cuối) đọc từ usageMetadata.totalTokenCount —
    dùng để báo chi phí thật trong docs/report.md thay vì ước lượng.
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
            # Giai doan bao cao cuoi (ADR-020): timeout/connect that ket noi khong
            # phai loi HTTP status, nen khong roi vao nhanh ben duoi - truoc day
            # thoat ngay khong retry.
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
    return text, candidate.get("finishReason"), total_tokens


def _parse_and_validate(raw: str, *, finish_reason: str | None) -> Answer:
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
    """Cổng bằng chứng — chạy sau cổng schema. Không kiểm quote có thật trong chunk,
    chỉ kiểm chunk_id có nằm trong ngữ cảnh đã đưa cho model hay không."""
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


def answer_question(
    question: str, chunks: list[RetrievedChunk], *, max_attempts: int = 2
) -> GroundedAnswer:
    """Luồng đầy đủ: 0 chunk thì abstain thẳng, có chunk thì gọi model có thử lại.

    Trần số lần thử: mỗi lượt gọi tốn tiền và tốn thời gian người dùng chờ, nên hết
    lượt là raise, không bao giờ fallback sang văn bản tự do — xem ngày 19.
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
