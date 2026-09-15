"""Cấp và xác minh JWT — bước 1/3 của việc thêm JWT (ADR-028): chỉ tiện ích, chưa
đụng route nào. `/ask` vẫn xác thực bằng API key y hệt trước; hàm ở đây chưa được
gọi từ đâu cả.

Dùng HS256 (đối xứng) chứ không phải RS256: chỉ một service vừa cấp vừa xác minh
token, không có bên thứ ba nào cần xác minh độc lập — bất đối xứng chỉ có ích khi
việc ký và việc xác minh tách rời nhau giữa các bên, thêm nó bây giờ là độ phức tạp
chưa cần dùng đến.

Luôn truyền ``algorithms=[...]`` tường minh khi decode, không bao giờ để PyJWT tự
đoán thuật toán từ header của token — đây là phòng vệ chống tấn công "algorithm
confusion" (kẻ tấn công tự ký một token bằng thuật toán khác, ví dụ ``none``, hòng
qua được bước xác minh).
"""

from datetime import UTC, datetime, timedelta

import jwt

from src.auth import AuthenticatedEmployee, AuthenticationError
from src.config import get_settings


def _require_secret() -> str:
    settings = get_settings()
    if not settings.jwt_secret_key:
        raise RuntimeError("JWT_SECRET_KEY rỗng — không thể ký/xác minh token. Kiểm tra .env.")
    return settings.jwt_secret_key


def issue_token(employee: AuthenticatedEmployee) -> str:
    """Ký một JWT mang danh tính đã xác thực — gọi SAU KHI đã xác minh employee bằng
    một đường xác thực khác (API key hôm nay; bước 2/3 sẽ thêm endpoint phát hành).

    Claims tối thiểu: ``sub`` (employee_id, đúng tên chuẩn JWT cho "subject"),
    ``role``/``department`` (để RBAC đọc thẳng từ token, không cần tra lại DB mỗi
    request — đổi lại: đổi role/department của một nhân viên sau khi token đã phát
    hành sẽ không phản ánh cho tới khi token đó hết hạn, một đánh đổi có chủ ý của
    JWT so với API key tra DB mỗi lần).
    """
    settings = get_settings()
    secret = _require_secret()
    now = datetime.now(UTC)
    payload = {
        "sub": employee.employee_id,
        "role": employee.role,
        "department": employee.department,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expiry_minutes),
    }
    return jwt.encode(payload, secret, algorithm=settings.jwt_algorithm)


def verify_token(token: str) -> AuthenticatedEmployee:
    """Xác minh chữ ký + hạn dùng, trả về danh tính. Mọi lỗi (hết hạn, sai chữ ký,
    thiếu claim, token hỏng) đều gộp thành ``AuthenticationError`` — cùng loại lỗi
    API key trả ra, để tầng gọi (``authenticate()``, bước 3/3) xử lý một cách thống
    nhất bất kể xác thực bằng phương thức nào."""
    settings = get_settings()
    secret = _require_secret()
    try:
        payload = jwt.decode(token, secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise AuthenticationError("token khong hop le hoac da het han") from exc

    employee_id = payload.get("sub")
    role = payload.get("role")
    department = payload.get("department")
    if not employee_id or not role or not department:
        raise AuthenticationError("token thieu claim bat buoc")

    return AuthenticatedEmployee(employee_id=employee_id, role=role, department=department)
