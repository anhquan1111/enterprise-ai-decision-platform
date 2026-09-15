"""Test cho src/auth.py — mock fetch_one, khong cham database that.

Giai doan xac thuc & do tin cay: dong lo hong AuthN da do o vault ngay 26
(AskRequest.role/department la truong tu khai, khong ai kiem chung). Test o day dam
bao lop xac thuc that su chan dung, khong chi ton tai tren giay.
"""

import hashlib

import pytest

from src import auth as auth_module
from src.auth import AuthenticationError, authenticate
from src.config import get_settings
from src.identity import AuthenticatedEmployee
from src.jwt_auth import issue_token


def make_row(
    employee_id: str = "emp_001", role: str = "employee", department: str = "sales"
) -> dict:
    return {"employee_id": employee_id, "role": role, "department": department}


def test_valid_bearer_token_authenticates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "fetch_one", lambda *a, **kw: make_row())

    employee = authenticate("Bearer bat-ky-key-nao-vi-da-mock-fetch_one")

    assert employee.employee_id == "emp_001"
    assert employee.role == "employee"
    assert employee.department == "sales"


def test_missing_header_raises() -> None:
    with pytest.raises(AuthenticationError):
        authenticate(None)


def test_header_without_bearer_prefix_raises() -> None:
    with pytest.raises(AuthenticationError):
        authenticate("just-a-raw-key-no-prefix")


def test_empty_key_after_bearer_raises() -> None:
    with pytest.raises(AuthenticationError):
        authenticate("Bearer ")


def test_key_not_matching_any_employee_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "fetch_one", lambda *a, **kw: None)

    with pytest.raises(AuthenticationError):
        authenticate("Bearer key-khong-ton-tai")


def test_key_is_hashed_before_querying_never_sent_as_plaintext(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kiểm tra thật, không chỉ tin docstring: tham số gửi cho fetch_one phải là hash,
    không phải chuỗi key gốc."""
    captured: dict = {}

    def spy_fetch_one(sql: str, params: dict) -> dict:  # type: ignore[type-arg]
        captured.update(params)
        return make_row()

    monkeypatch.setattr(auth_module, "fetch_one", spy_fetch_one)

    authenticate("Bearer chuoi-key-ro-rang")

    expected_hash = hashlib.sha256(b"chuoi-key-ro-rang").hexdigest()
    assert captured["hash"] == expected_hash
    assert "chuoi-key-ro-rang" not in captured.values()


def test_jwt_bearer_token_authenticates_via_jwt_path_not_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-028 bước 3/3: một JWT hợp lệ phải xác thực được KHÔNG qua fetch_one —
    authenticate() phân biệt bằng hình dạng token (JWT luôn có đúng 2 dấu '.'),
    không thử API key trước rồi mới thử JWT."""
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-du-dai-de-qua-canh-bao-do-dai")
    get_settings.cache_clear()

    def fail_if_called(*a: object, **kw: object) -> None:
        raise AssertionError("khong duoc goi fetch_one khi token la JWT")

    monkeypatch.setattr(auth_module, "fetch_one", fail_if_called)

    token = issue_token(
        AuthenticatedEmployee(employee_id="emp_042", role="manager", department="hr")
    )

    employee = authenticate(f"Bearer {token}")

    assert employee.employee_id == "emp_042"
    assert employee.role == "manager"
    assert employee.department == "hr"


def test_malformed_jwt_shaped_token_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Token có đúng 2 dấu '.' (giống hình dạng JWT) nhưng nội dung rác phải bị từ
    chối rõ ràng, không rơi nhầm sang đường tra API key."""
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-du-dai-de-qua-canh-bao-do-dai")
    get_settings.cache_clear()

    with pytest.raises(AuthenticationError):
        authenticate("Bearer khong.phai.jwt")


def test_api_key_without_dots_still_uses_db_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Xác nhận API key (không có dấu '.') vẫn đi đúng đường tra DB cũ, không bị
    route nhầm sang xác minh JWT."""
    monkeypatch.setattr(auth_module, "fetch_one", lambda *a, **kw: make_row())

    employee = authenticate("Bearer mot-api-key-binh-thuong-khong-co-dau-cham")

    assert employee.employee_id == "emp_001"
