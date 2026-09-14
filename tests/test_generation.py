"""Test cho generation.py — mock httpx.post, không gọi Gemini thật.

Cùng nguyên tắc với test_api.py: unit test không phụ thuộc mạng. Test end-to-end với
Gemini thật nằm trong test_ask_live.py, đánh dấu ``live_llm``.
"""

import json

import httpx
import pytest

from src.generation import (
    Answer,
    Citation,
    SchemaFailure,
    answer_question,
    build_prompt,
    check_grounding,
)
from src.retrieval import RetrievedChunk


def make_chunk(chunk_id: str = "A#0", text: str = "Noi dung mau") -> RetrievedChunk:
    doc_id, index = chunk_id.split("#")
    return RetrievedChunk(
        doc_id=doc_id,
        chunk_index=int(index),
        chunk_text=text,
        department="hr",
        access_level="employee",
        distance=0.1,
    )


def fake_gemini_response(
    monkeypatch: pytest.MonkeyPatch, texts: list[tuple[int, str]]
) -> list[str]:
    """Giả lập chuỗi response HTTP liên tiếp từ Gemini.

    Args:
        texts: Danh sách (status_code, noi_dung_text). status_code khac 200 mo phong
            loi tam thoi (429/5xx); noi_dung_text la text cua candidate khi 200.
    """
    calls: list[str] = []
    responses = list(texts)

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        calls.append(url)
        status, text = responses.pop(0)
        request = httpx.Request("POST", url)
        if status != 200:
            return httpx.Response(status, request=request, json={"error": "tam thoi"})
        body = {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]}
        return httpx.Response(200, request=request, json=body)

    monkeypatch.setattr(httpx, "post", fake_post)
    return calls


# ── build_prompt ─────────────────────────────────────────────────


def test_build_prompt_rejects_empty_chunk_list() -> None:
    with pytest.raises(ValueError, match="rỗng"):
        build_prompt("cau hoi", [])


def test_build_prompt_includes_chunk_id_and_question() -> None:
    prompt = build_prompt("cau hoi mau", [make_chunk("A#0", "noi dung A")])

    assert "A#0" in prompt
    assert "noi dung A" in prompt
    assert "cau hoi mau" in prompt


# ── check_grounding ──────────────────────────────────────────────


def test_check_grounding_flags_fabricated_citation() -> None:
    answer = Answer(
        answer="tra loi",
        citations=[Citation(chunk_id="Z#9", quote="bia dat")],
        abstained=False,
    )

    problems = check_grounding(answer, allowed_chunk_ids={"A#0"})

    assert any("ngoài context" in p for p in problems)


def test_check_grounding_flags_answer_without_citation() -> None:
    answer = Answer(answer="tra loi khong nguon", citations=[], abstained=False)

    problems = check_grounding(answer, allowed_chunk_ids={"A#0"})

    assert any("không có citation" in p for p in problems)


def test_check_grounding_passes_valid_answer() -> None:
    answer = Answer(
        answer="tra loi dung",
        citations=[Citation(chunk_id="A#0", quote="trich dan")],
        abstained=False,
    )

    assert check_grounding(answer, allowed_chunk_ids={"A#0"}) == []


# ── answer_question: đường không gọi mạng ───────────────────────


def test_answer_question_abstains_without_network_call_when_no_chunks(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """0 chunk thì abstain thẳng — không gọi Gemini để nó tự bịa từ kiến thức nền."""
    calls: list[str] = []
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: calls.append("called"))

    result = answer_question("cau hoi", [])

    assert result.answer.abstained is True
    assert calls == []


# ── answer_question: retry vì sai schema ────────────────────────


def test_answer_question_retries_after_schema_failure(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    good = json.dumps({"answer": "dung roi", "citations": [], "abstained": True})
    calls = fake_gemini_response(monkeypatch, [(200, "khong phai json"), (200, good)])

    result = answer_question("cau hoi", [make_chunk()])

    assert result.attempts == 2
    assert len(calls) == 2
    assert result.answer.answer == "dung roi"


def test_answer_question_gives_up_after_max_attempts(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Hết lượt thử thì raise, không fallback sang văn bản tự do."""
    fake_gemini_response(monkeypatch, [(200, "sai 1"), (200, "sai 2")])

    with pytest.raises(SchemaFailure, match="sau 2 lần"):
        answer_question("cau hoi", [make_chunk()], max_attempts=2)


# ── answer_question: retry vì lỗi mạng tạm thời ─────────────────


def test_answer_question_retries_on_transient_503(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    good = json.dumps({"answer": "on dinh roi", "citations": [], "abstained": True})
    monkeypatch.setattr("src.generation._NETWORK_RETRY_BACKOFF_S", 0.0)
    calls = fake_gemini_response(monkeypatch, [(503, ""), (200, good)])

    result = answer_question("cau hoi", [make_chunk()])

    assert len(calls) == 2
    assert result.answer.answer == "on dinh roi"


def test_answer_question_does_not_retry_on_client_error(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """400 là lỗi request, không tự sửa được bằng cách gọi lại — raise ngay."""
    fake_gemini_response(monkeypatch, [(400, "")])

    with pytest.raises(httpx.HTTPStatusError):
        answer_question("cau hoi", [make_chunk()])


# ── grounding problems không chặn response ───────────────────────


def test_answer_question_returns_grounding_problems_without_raising(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Bịa nguồn là vấn đề nghiêm trọng, nhưng answer_question không raise vì nó —
    D4 cần response đầy đủ để ghi audit log, không phải một exception im lặng."""
    bad = json.dumps(
        {"answer": "bia dat", "citations": [{"chunk_id": "Z#9", "quote": "x"}], "abstained": False}
    )
    fake_gemini_response(monkeypatch, [(200, bad)])

    result = answer_question("cau hoi", [make_chunk("A#0")])

    assert result.answer.answer == "bia dat"
    assert any("ngoài context" in p for p in result.grounding_problems)
