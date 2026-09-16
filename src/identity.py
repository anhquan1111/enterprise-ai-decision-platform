"""Định nghĩa kiểu dữ liệu danh tính và ngoại lệ xác thực dùng chung trong hệ thống."""

from dataclasses import dataclass


# 1. Custom Exceptions
class AuthenticationError(Exception):
    """Ngoại lệ xác thực chung khi thông tin định danh thiếu, sai định dạng hoặc hết hạn.

    Luôn map về HTTP 401 với thông điệp chung chung, không nói rõ chi tiết (ví dụ: 'key tồn tại
    nhưng sai hash') nhằm ngăn chặn kẻ tấn công dò quét sự tồn tại của tài khoản/key.
    """


# 2. Authenticated Identity Contract
@dataclass(frozen=True)
class AuthenticatedEmployee:
    """Đối tượng danh tính nhân viên sau khi xác thực thành công (từ API Key hoặc JWT).

    frozen=True: Bất biến (immutable) tuyệt đối để ngăn chặn mã độc hoặc code hạ nguồn tự ý
    sửa đổi role/department của nhân viên trên RAM sau khi đã qua cửa bảo vệ.
    """

    employee_id: str
    role: str
    department: str
