"""Test cho src/ocr.py — mock httpx.post, khong goi Gemini vision that.

Cung nguyen tac voi test_generation.py/test_agent_router.py: unit test khong phu
thuoc mang. Test end-to-end that (PDF that -> Gemini that -> do CER) nam trong
test_ocr_live.py, danh dau live_llm.
"""

import base64

import httpx
import pytest

from src.ocr import OcrError, extract_text


def fake_gemini_response(
    monkeypatch: pytest.MonkeyPatch, texts: list[tuple[int, str]]
) -> list[dict]:
    calls: list[dict] = []
    responses = list(texts)

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        calls.append({"url": url, "json": kwargs.get("json")})
        status, text = responses.pop(0)
        request = httpx.Request("POST", url)
        if status != 200:
            return httpx.Response(status, request=request, json={"error": "tam thoi"})
        resp_body = {
            "candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]
        }
        return httpx.Response(200, request=request, json=resp_body)

    monkeypatch.setattr(httpx, "post", fake_post)
    return calls


def test_rejects_unsupported_mime_type() -> None:
    with pytest.raises(ValueError, match="mime_type"):
        extract_text(b"data", mime_type="text/plain")


def test_extracts_text_and_sends_base64_inline_data(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = fake_gemini_response(monkeypatch, [(200, "Van ban da trich xuat.")])

    result = extract_text(b"fake pdf bytes", mime_type="application/pdf")

    assert result == "Van ban da trich xuat."
    sent_payload = calls[0]["json"]
    inline = sent_payload["contents"][0]["parts"][0]["inlineData"]
    assert inline["mimeType"] == "application/pdf"
    assert base64.b64decode(inline["data"]) == b"fake pdf bytes"


def test_retries_transient_network_error_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.ocr._NETWORK_RETRY_BACKOFF_S", 0.0)
    calls = fake_gemini_response(monkeypatch, [(503, ""), (200, "thanh cong sau retry")])

    result = extract_text(b"anh", mime_type="image/png")

    assert result == "thanh cong sau retry"
    assert len(calls) == 2


def test_raises_after_retries_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.ocr._NETWORK_RETRY_BACKOFF_S", 0.0)
    fake_gemini_response(monkeypatch, [(503, ""), (503, ""), (503, "")])

    with pytest.raises(httpx.HTTPStatusError):
        extract_text(b"anh", mime_type="image/jpeg")


def test_empty_response_raises_ocr_error_not_silently_returns_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_gemini_response(monkeypatch, [(200, "")])

    with pytest.raises(OcrError):
        extract_text(b"anh", mime_type="image/png")


def test_client_error_status_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """400 (request sai) không tự sửa được bằng cách gọi lại — khác 429/5xx."""
    calls = fake_gemini_response(monkeypatch, [(400, "")])

    with pytest.raises(httpx.HTTPStatusError):
        extract_text(b"anh", mime_type="image/png")

    assert len(calls) == 1
