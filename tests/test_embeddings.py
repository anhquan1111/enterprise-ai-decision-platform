"""Test cho embeddings.py — mock httpx.post, không gọi Gemini thật.

conftest.py cách ly Settings khỏi .env cho mọi test (đúng thiết kế của giai đoạn
tầng dữ liệu: một test không
được phụ thuộc máy nào đang chạy nó có .env gì). Vì vậy mỗi test ở đây tự đặt một key
giả qua biến môi trường, rồi xoá cache Settings để giá trị mới có hiệu lực.
"""

import httpx
import pytest

from src.config import get_settings
from src.embeddings import embed


@pytest.fixture(autouse=True)
def fake_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "fake-test-key")
    get_settings.cache_clear()


def fake_response(values: list[float]) -> httpx.Response:
    request = httpx.Request("POST", "https://example.test")
    return httpx.Response(200, request=request, json={"embedding": {"values": values}})


def test_embed_returns_vector_of_configured_dimension(monkeypatch: pytest.MonkeyPatch) -> None:
    dim = get_settings().embedding_dim
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: fake_response([0.1] * dim))

    result = embed("noi dung", task_type="RETRIEVAL_DOCUMENT")

    assert len(result) == dim


def test_embed_raises_on_dimension_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gemini trả sai số chiều phải báo lỗi ngay, không âm thầm ghi lệch vào cột vector(384)."""
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: fake_response([0.1] * 10))

    with pytest.raises(ValueError, match="chiều"):
        embed("noi dung", task_type="RETRIEVAL_DOCUMENT")


def test_embed_raises_when_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Thiếu key phải lỗi rõ ràng trước khi gọi mạng, không phải một 401 khó hiểu."""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    get_settings.cache_clear()

    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        embed("noi dung", task_type="RETRIEVAL_DOCUMENT")


def test_embed_sends_task_type_in_request_body(monkeypatch: pytest.MonkeyPatch) -> None:
    dim = get_settings().embedding_dim
    captured: dict[str, object] = {}

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        captured["json"] = kwargs["json"]
        return fake_response([0.1] * dim)

    monkeypatch.setattr(httpx, "post", fake_post)

    embed("cau hoi", task_type="RETRIEVAL_QUERY")

    body = captured["json"]
    assert isinstance(body, dict)
    assert body["taskType"] == "RETRIEVAL_QUERY"


def test_embed_retries_after_transient_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """Giai đoạn báo cáo cuối (ADR-024): phát hiện thật khi chạy held-out v2 — một lần
    503 thoáng qua từ gemini-embedding-001 trước đây làm chết hẳn mọi câu hỏi cần docs
    retrieval, trong khi generation.py/router.py đã có retry từ lâu. Test này khoá lại
    hành vi retry mới, cùng mẫu với test_generation.py."""
    dim = get_settings().embedding_dim
    monkeypatch.setattr("src.embeddings._NETWORK_RETRY_BACKOFF_S", 0.0)
    responses: list[httpx.Response] = [
        httpx.Response(503, request=httpx.Request("POST", "https://example.test"), json={}),
        fake_response([0.1] * dim),
    ]

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        return responses.pop(0)

    monkeypatch.setattr(httpx, "post", fake_post)

    result = embed("cau hoi", task_type="RETRIEVAL_QUERY")

    assert len(result) == dim


def test_embed_raises_after_retries_exhausted_on_persistent_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.embeddings._NETWORK_RETRY_BACKOFF_S", 0.0)
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *a, **kw: httpx.Response(
            503, request=httpx.Request("POST", "https://example.test"), json={}
        ),
    )

    with pytest.raises(httpx.HTTPStatusError):
        embed("cau hoi", task_type="RETRIEVAL_QUERY")


def test_embed_retries_after_real_network_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    dim = get_settings().embedding_dim
    monkeypatch.setattr("src.embeddings._NETWORK_RETRY_BACKOFF_S", 0.0)
    responses: list[object] = [httpx.TimeoutException("het gio"), fake_response([0.1] * dim)]

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        assert isinstance(item, httpx.Response)
        return item

    monkeypatch.setattr(httpx, "post", fake_post)

    result = embed("cau hoi", task_type="RETRIEVAL_QUERY")

    assert len(result) == dim
