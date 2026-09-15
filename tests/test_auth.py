"""Test cho src/auth.py — mock fetch_one, khong cham database that.

D4: dong lo hong AuthN da do o vault ngay 26 (AskRequest.role/department la truong tu
khai, khong ai kiem chung). Test o day dam bao lop xac thuc that su chan dung, khong
chi ton tai tren giay.
"""

import hashlib

import pytest

from src import auth as auth_module
from src.auth import AuthenticationError, authenticate


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
