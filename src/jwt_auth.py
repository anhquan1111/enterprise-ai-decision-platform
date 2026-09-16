"""Cấp phát và xác minh JWT token (HS256) cho nhân viên phục vụ xác thực nhanh trên RAM."""

# 1. Imports & Secret Validation
from datetime import UTC, datetime, timedelta

import jwt

from src.config import get_settings
from src.identity import AuthenticatedEmployee, AuthenticationError


def _require_secret() -> str:
    """Kiểm tra và lấy secret key từ cấu hình; ném lỗi nếu chưa được thiết lập."""
    settings = get_settings()
    if not settings.jwt_secret_key:
        raise RuntimeError("JWT_SECRET_KEY rỗng — không thể ký/xác minh token. Kiểm tra .env.")
    return settings.jwt_secret_key


# 2. Token Issuance (issue_token)
def issue_token(employee: AuthenticatedEmployee) -> str:
    """Ký phát hành JWT token ngắn hạn (HS256) chứa danh tính và quyền hạn nhân viên."""
    settings = get_settings()
    secret = _require_secret()
    now = datetime.now(UTC)
    # Claims: sub (ID nhân viên), role/dept (để RBAC đọc thẳng trên RAM), exp (hạn 60m)
    payload = {
        "sub": employee.employee_id,
        "role": employee.role,
        "department": employee.department,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expiry_minutes),
    }
    return jwt.encode(payload, secret, algorithm=settings.jwt_algorithm)


# 3. Token Verification (verify_token)
def verify_token(token: str) -> AuthenticatedEmployee:
    """Xác minh chữ ký và thời hạn JWT trong RAM; truyền algorithms rõ ràng chống giả mạo."""
    settings = get_settings()
    secret = _require_secret()
    try:
        # Luôn truyền algorithms=[...] tường minh để chống tấn công Algorithm Confusion (alg: none)
        payload = jwt.decode(token, secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise AuthenticationError("token khong hop le hoac da het han") from exc

    employee_id = payload.get("sub")
    role = payload.get("role")
    department = payload.get("department")
    if not employee_id or not role or not department:
        raise AuthenticationError("token thieu claim bat buoc")

    return AuthenticatedEmployee(employee_id=employee_id, role=role, department=department)
