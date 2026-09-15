"""Test cho src/agent/router.py — mock httpx.post, khong goi Gemini that.

Cung nguyen tac voi test_generation.py: retry mang tach biet khoi retry schema.
"""

import httpx
import pytest

from src.agent.router import RouterSchemaFailure, route


def fake_gemini_response(
    monkeypatch: pytest.MonkeyPatch, texts: list[tuple[int, str]], *, total_tokens: int = 0
) -> list[str]:
    calls: list[str] = []
    responses = list(texts)

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        calls.append(url)
        status, text = responses.pop(0)
        request = httpx.Request("POST", url)
        if status != 200:
            return httpx.Response(status, request=request, json={"error": "tam thoi"})
        body = {
            "candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}],
            "usageMetadata": {"totalTokenCount": total_tokens},
        }
        return httpx.Response(200, request=request, json=body)

    monkeypatch.setattr(httpx, "post", fake_post)
    return calls


def test_route_docs_only(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_gemini_response(monkeypatch, [(200, '{"tools": ["docs"]}')], total_tokens=123)

    result = route("Nhan vien duoc bao nhieu ngay phep?")

    assert result.plan.tools == ["docs"]
    assert result.plan.sql_args is None
    assert (
        result.total_tokens == 123
    )  # giai đoạn báo cáo cuối: token thật đọc từ usageMetadata, không đoán


def test_route_sql_with_args(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_gemini_response(
        monkeypatch,
        [
            (
                200,
                '{"tools": ["sql"], "sql_args": {"department": "sales", '
                '"month_from": "2026-01-01", "month_to": "2026-06-01"}}',
            )
        ],
    )

    result = route("Doanh thu sales tu dau nam den gio bao nhieu?")

    assert result.plan.tools == ["sql"]
    assert result.plan.sql_args is not None
    assert result.plan.sql_args.department == "sales"


def test_route_retries_after_malformed_json_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = fake_gemini_response(
        monkeypatch,
        [(200, "khong phai json"), (200, '{"tools": ["docs"]}')],
        total_tokens=50,
    )

    result = route("cau hoi bat ky")

    assert result.plan.tools == ["docs"]
    assert len(calls) == 2
    assert (
        result.total_tokens == 100
    )  # giai đoạn báo cáo cuối: cả 2 lượt gọi đều tốn tiền, phải cộng dồn


def test_route_raises_after_schema_retry_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_gemini_response(
        monkeypatch, [(200, "van khong phai json"), (200, "van sai")], total_tokens=40
    )

    with pytest.raises(RouterSchemaFailure) as exc_info:
        route("cau hoi bat ky")

    # Giai đoạn báo cáo cuối: dù cuối cùng thất bại, hai lượt gọi đã thử vẫn tốn
    # tiền thật — không phải 0.
    assert exc_info.value.total_tokens == 80


def test_route_retries_transient_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.agent.router._NETWORK_RETRY_BACKOFF_S", 0.0)
    calls = fake_gemini_response(monkeypatch, [(503, ""), (200, '{"tools": ["docs"]}')])

    result = route("cau hoi bat ky")

    assert result.plan.tools == ["docs"]
    assert len(calls) == 2


def test_route_retries_after_real_timeout_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """Giai doan bao cao cuoi (ADR-020): httpx.TimeoutException khi GOI httpx.post khong phai status
    code, trước đây thoát ngay không retry (held-out H02, xem ADR-019)."""
    monkeypatch.setattr("src.agent.router._NETWORK_RETRY_BACKOFF_S", 0.0)
    calls: list[str] = []
    responses: list[object] = [httpx.TimeoutException("het gio"), (200, '{"tools": ["docs"]}')]

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        calls.append(url)
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        status, text = item  # type: ignore[misc]
        body = {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]}
        return httpx.Response(status, request=httpx.Request("POST", url), json=body)

    monkeypatch.setattr(httpx, "post", fake_post)

    result = route("cau hoi bat ky")

    assert result.plan.tools == ["docs"]
    assert len(calls) == 2


def test_route_raises_after_timeout_exhausts_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.agent.router._NETWORK_RETRY_BACKOFF_S", 0.0)
    monkeypatch.setattr(
        httpx, "post", lambda *a, **kw: (_ for _ in ()).throw(httpx.ConnectError("mat mang"))
    )

    with pytest.raises(httpx.ConnectError):
        route("cau hoi bat ky")
