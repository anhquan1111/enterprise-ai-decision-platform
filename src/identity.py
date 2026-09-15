"""Kiểu dữ liệu danh tính dùng chung giữa auth.py (API key) và jwt_auth.py (JWT).

Tách riêng module này chỉ để phá vòng import: bước 3/3 của ADR-028 cần
``auth.py::authenticate()`` gọi ``jwt_auth.py::verify_token()``, nhưng
``jwt_auth.py`` từ bước 1/3 đã import ``AuthenticatedEmployee``/``AuthenticationError``
từ ``auth.py`` — hai module import lẫn nhau sẽ vỡ ngay từ lúc import. Đưa hai kiểu
này ra một module không phụ thuộc gì (không DB, không JWT) để cả hai cùng import từ
đây, không import lẫn nhau.
"""

from dataclasses import dataclass


class AuthenticationError(Exception):
    """Header thiếu, sai định dạng, hoặc thông tin xác thực (API key hay JWT) không
    hợp lệ. Luôn trả 401, không bao giờ nói rõ lý do cụ thể (vd "key tồn tại nhưng
    sai") — tránh lộ thông tin giúp kẻ tấn công dò key/token thật."""


@dataclass(frozen=True)
class AuthenticatedEmployee:
    employee_id: str
    role: str
    department: str
