"""Giai doan xac thuc & do tin cay: Xac thuc that bang API key, dong lo hong da do
duoc o ngay 26 (vault) - truoc day AskRequest.role/department la truong du lieu tu
khai, khong ai kiem chung ca.

Chi bam SHA-256 va so voi cot employees.api_key_hash (sql/06_auth.sql) - khong bao
gio luu hoac log key dang plaintext. Xem scripts/issue_api_keys.py de cap key.

Tu buoc 3/3 cua ADR-028, authenticate() chap nhan CA HAI: API key (nhu tu truoc) va
JWT (cap qua POST /auth/token, xem jwt_auth.py). Phan biet bang hinh dang: JWT luon
la ba doan base64url cach nhau boi ".", API key (secrets.token_urlsafe) khong bao
gio chua ky tu "." - kiem dinh dang truoc, khong thu ca hai duong roi bat loi, vi
mot API key tinh co dung dang "." se bi hieu nham thanh JWT hong thay vi API key sai
(hai thong bao loi khac nhau se ro rang hon cho nguoi debug).
"""

import hashlib

from src.db import fetch_one
from src.identity import AuthenticatedEmployee, AuthenticationError
from src.jwt_auth import verify_token

__all__ = ["AuthenticatedEmployee", "AuthenticationError", "authenticate"]


def _hash(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def _looks_like_jwt(token: str) -> bool:
    return token.count(".") == 2


def _authenticate_api_key(api_key: str) -> AuthenticatedEmployee:
    row = fetch_one(
        "SELECT employee_id, role, department FROM employees WHERE api_key_hash = %(hash)s",
        {"hash": _hash(api_key)},
    )
    if row is None:
        raise AuthenticationError("api key khong khop nhan vien nao")

    return AuthenticatedEmployee(
        employee_id=row["employee_id"], role=row["role"], department=row["department"]
    )


def authenticate(authorization_header: str | None) -> AuthenticatedEmployee:
    """Xac minh header ``Authorization: Bearer <api_key_hoac_jwt>``, tra ve danh
    tinh THAT.

    Day la nguon su that DUY NHAT cho role/department dung de RBAC - khong phai
    truong role/department trong body request (xem ADR ve AuthN, giai doan xac thuc
    & do tin cay).
    """
    if not authorization_header or not authorization_header.startswith("Bearer "):
        raise AuthenticationError("thieu hoac sai dinh dang header Authorization")

    token = authorization_header.removeprefix("Bearer ").strip()
    if not token:
        raise AuthenticationError("token rong")

    if _looks_like_jwt(token):
        return verify_token(token)
    return _authenticate_api_key(token)
