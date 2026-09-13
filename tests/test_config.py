"""Tests for configuration handling."""

from src.config import Settings


def test_database_url_is_built_from_parts() -> None:
    """The connection string must be assembled from the individual settings.

    Keeping host/port/db separate (instead of one DATABASE_URL string) is what
    lets compose override only POSTGRES_HOST for the container network while the
    host-side defaults stay untouched.
    """
    settings = Settings(
        postgres_host="db",
        postgres_port=5432,
        postgres_db="enterprise_ai",
        postgres_user="app",
        postgres_password="secret",
        postgres_connect_timeout=5,
    )

    assert settings.database_url == (
        "postgresql://app:secret@db:5432/enterprise_ai?connect_timeout=5"
    )


def test_database_url_always_carries_a_connect_timeout() -> None:
    """An unreachable database must fail in bounded time, not block the caller.

    libpq defaults to waiting indefinitely, so the timeout is not a tuning knob
    here — leaving it out is what turns a connection error into a hang. See
    docs/decisions.md ADR-005.
    """
    url = Settings().database_url

    assert "connect_timeout=" in url
    assert Settings().postgres_connect_timeout > 0


def test_database_host_defaults_to_ipv4_literal() -> None:
    """Default to 127.0.0.1, not the name "localhost".

    "localhost" resolves IPv6-first on the development host while compose
    publishes the port on IPv4 only, so every connection pays for a dead address
    before falling back (measured: 5.08s vs 0.04s).
    """
    assert Settings().postgres_host == "127.0.0.1"


def test_llm_model_is_pinned_not_a_latest_alias() -> None:
    """Tên model phải cố định, không dùng alias kiểu "-latest".

    Alias trỏ sang model mới theo thời gian, nên một số đo báo hôm nay sẽ không so được
    với số đo tháng sau, và không ai biết vì sao. Xem docs/decisions.md ADR-002.
    """
    model = Settings().llm_model

    assert model
    assert "latest" not in model


def test_api_key_defaults_to_empty_not_placeholder() -> None:
    """Thiếu key thì phải rỗng để lỗi rõ ràng, không phải một giá trị trông như thật.

    Assert bằng boolean chứ không so sánh giá trị: nếu test này fail trên một máy có
    .env thật, một assertion so sánh chuỗi sẽ **in luôn secret** vào output và vào log
    CI. Cách ly khỏi .env do conftest lo; đây là lớp phòng thứ hai.
    """
    assert not Settings().llm_api_key
