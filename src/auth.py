"""D4: Xac thuc that bang API key, dong lo hong da do duoc o ngay 26 (vault) - truoc
day AskRequest.role/department la truong du lieu tu khai, khong ai kiem chung ca.

Chi bam SHA-256 va so voi cot employees.api_key_hash (sql/06_auth.sql) - khong bao
gio luu hoac log key dang plaintext. Xem scripts/issue_api_keys.py de cap key.
"""

import hashlib
from dataclasses import dataclass

from src.db import fetch_one


class AuthenticationError(Exception):
    """Header thieu, sai dinh dang, hoac key khong khop nhan vien nao. Luon tra 401,
    khong bao gio noi ro ly do cu the (vd "key ton tai nhung sai") - tranh lo thong
    tin giup ke tan cong do key that."""


@dataclass(frozen=True)
class AuthenticatedEmployee:
    employee_id: str
    role: str
    department: str


def _hash(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def authenticate(authorization_header: str | None) -> AuthenticatedEmployee:
    """Xac minh header ``Authorization: Bearer <api_key>``, tra ve danh tinh THAT.

    Day la nguon su that DUY NHAT cho role/department dung de RBAC - khong phai
    truong role/department trong body request (xem ADR ve AuthN, D4).
    """
    if not authorization_header or not authorization_header.startswith("Bearer "):
        raise AuthenticationError("thieu hoac sai dinh dang header Authorization")

    api_key = authorization_header.removeprefix("Bearer ").strip()
    if not api_key:
        raise AuthenticationError("api key rong")

    row = fetch_one(
        "SELECT employee_id, role, department FROM employees WHERE api_key_hash = %(hash)s",
        {"hash": _hash(api_key)},
    )
    if row is None:
        raise AuthenticationError("api key khong khop nhan vien nao")

    return AuthenticatedEmployee(
        employee_id=row["employee_id"], role=row["role"], department=row["department"]
    )
