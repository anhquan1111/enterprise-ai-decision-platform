"""Xác thực danh tính (AuthN): Xác minh API key băm SHA-256 hoặc JWT token để lấy nhân viên."""

# 1. Imports & Exports
import hashlib

from src.db import fetch_one
from src.identity import AuthenticatedEmployee, AuthenticationError
from src.jwt_auth import verify_token

__all__ = ["AuthenticatedEmployee", "AuthenticationError", "authenticate"]


# 2. Helper Functions: Hashing & Token Inspection
def _hash(api_key: str) -> str:
    """Băm SHA-256 của API key; tuyệt đối không lưu hoặc so sánh key ở dạng plaintext."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def _looks_like_jwt(token: str) -> bool:
    """JWT chuẩn luôn gồm 3 phần tách bởi 2 dấu chấm (Header.Payload.Signature)."""
    return token.count(".") == 2


# 3. Authentication Strategies: API Key Lookup
def _authenticate_api_key(api_key: str) -> AuthenticatedEmployee:
    """Tra cứu mã băm SHA-256 trong bảng employees để xác định danh tính nhân viên."""
    row = fetch_one(
        "SELECT employee_id, role, department FROM employees WHERE api_key_hash = %(hash)s",
        {"hash": _hash(api_key)},
    )
    if row is None:
        raise AuthenticationError("api key khong khop nhan vien nao")

    return AuthenticatedEmployee(
        employee_id=row["employee_id"], role=row["role"], department=row["department"]
    )


# 4. Public Gateway: authenticate()
def authenticate(authorization_header: str | None) -> AuthenticatedEmployee:
    """Xác thực Authorization: Bearer <token>, trả về danh tính thật làm căn cứ cho RBAC."""
    if not authorization_header or not authorization_header.startswith("Bearer "):
        raise AuthenticationError("thieu hoac sai dinh dang header Authorization")

    token = authorization_header.removeprefix("Bearer ").strip()
    if not token:
        raise AuthenticationError("token rong")

    # Phân nhánh theo định dạng: JWT giải mã trên RAM (0ms), API key tra cứu DB
    if _looks_like_jwt(token):
        return verify_token(token)
    return _authenticate_api_key(token)
