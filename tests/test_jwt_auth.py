"""Test cho src/jwt_auth.py — không gọi mạng, không chạm database.

Bước 1/3 của việc thêm JWT (ADR-028): các hàm ở đây chưa được gọi từ route nào,
nên test tập trung vào đúng tính chất bảo mật của việc ký/xác minh token — round
trip đúng, chữ ký sai bị từ chối, hết hạn bị từ chối, và tấn công "algorithm
confusion" (ký bằng một thuật toán khác thuật toán được cấu hình) bị từ chối.
"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from src.auth import AuthenticatedEmployee, AuthenticationError
from src.config import get_settings
from src.jwt_auth import issue_token, verify_token


@pytest.fixture(autouse=True)
def fake_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-khong-dung-that-du-dai-32-byte")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("JWT_EXPIRY_MINUTES", "60")
    get_settings.cache_clear()


def make_employee(
    employee_id: str = "emp_001", role: str = "employee", department: str = "sales"
) -> AuthenticatedEmployee:
    return AuthenticatedEmployee(employee_id=employee_id, role=role, department=department)


def test_issue_then_verify_round_trip_returns_same_identity() -> None:
    token = issue_token(make_employee())

    employee = verify_token(token)

    assert employee.employee_id == "emp_001"
    assert employee.role == "employee"
    assert employee.department == "sales"


def test_verify_rejects_tampered_signature() -> None:
    token = issue_token(make_employee())
    tampered = token[:-4] + ("A" if token[-4] != "A" else "B") + token[-3:]

    with pytest.raises(AuthenticationError):
        verify_token(tampered)


def test_verify_rejects_expired_token(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    now = datetime.now(UTC)
    expired_payload = {
        "sub": "emp_001",
        "role": "employee",
        "department": "sales",
        "iat": now - timedelta(minutes=120),
        "exp": now - timedelta(minutes=60),
    }
    expired_token = jwt.encode(
        expired_payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )

    with pytest.raises(AuthenticationError):
        verify_token(expired_token)


def test_verify_rejects_token_signed_with_wrong_secret() -> None:
    now = datetime.now(UTC)
    payload = {
        "sub": "emp_001",
        "role": "employee",
        "department": "sales",
        "iat": now,
        "exp": now + timedelta(minutes=60),
    }
    forged = jwt.encode(payload, "khong-phai-secret-that", algorithm="HS256")

    with pytest.raises(AuthenticationError):
        verify_token(forged)


def test_verify_rejects_algorithm_confusion_attack() -> None:
    """Token tự ký bằng thuật toán KHÁC thuật toán đã cấu hình (HS256) phải bị từ
    chối — verify_token() truyền algorithms=[...] tường minh, không để PyJWT tự
    đoán thuật toán từ header của token kẻ tấn công gửi lên."""
    now = datetime.now(UTC)
    payload = {
        "sub": "emp_001",
        "role": "employee",
        "department": "sales",
        "iat": now,
        "exp": now + timedelta(minutes=60),
    }
    forged = jwt.encode(payload, "bat-ky-chuoi-nao", algorithm="HS384")

    with pytest.raises(AuthenticationError):
        verify_token(forged)


def test_verify_rejects_missing_required_claim() -> None:
    settings = get_settings()
    now = datetime.now(UTC)
    incomplete_payload = {
        "sub": "emp_001",
        # thiếu "role" va "department"
        "iat": now,
        "exp": now + timedelta(minutes=60),
    }
    token = jwt.encode(
        incomplete_payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )

    with pytest.raises(AuthenticationError):
        verify_token(token)


def test_issue_raises_when_secret_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    get_settings.cache_clear()

    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        issue_token(make_employee())


def test_verify_raises_when_secret_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    token = issue_token(make_employee())
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    get_settings.cache_clear()

    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        verify_token(token)
