"""Cấu hình chung cho test.

Bất biến quan trọng nhất ở đây: **test không bao giờ đọc `.env` của máy đang chạy.**

Không có nó thì kết quả test phụ thuộc vào việc máy đó có `.env` gì — CI xanh mà máy dev
đỏ, hoặc ngược lại. Tệ hơn: một assertion so sánh với giá trị thật sẽ in secret ra
output, và output đó đi vào log CI.
"""

from collections.abc import Generator

import pytest

from src.config import Settings, get_settings


@pytest.fixture(autouse=True)
def isolate_settings_from_local_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    """Ngắt Settings khỏi file .env trong suốt test.

    autouse nên áp cho mọi test, kể cả test viết sau này — người viết không phải nhớ.
    """
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
