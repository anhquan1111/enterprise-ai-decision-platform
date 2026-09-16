"""Quy tắc phân quyền RBAC: Xác định phạm vi truy cập tài liệu và số liệu SQL theo vai trò."""

# 1. Phân quyền Tài liệu (Document RBAC Hierarchy & Constants)
# File này là thuần Python (không import pandas/numpy) để phục vụ API serving siêu nhẹ.

# Thứ bậc quyền tài liệu: Role cao hơn được đọc tài liệu ở mức của mình và mọi mức thấp hơn
ROLE_VISIBLE_LEVELS: dict[str, tuple[str, ...]] = {
    "employee": ("employee",),
    "manager": ("employee", "manager"),
    "executive": ("employee", "manager", "executive"),
}

ALLOWED_ACCESS_LEVELS: frozenset[str] = frozenset({"employee", "manager", "executive"})
ALLOWED_DEPARTMENTS: frozenset[str] = frozenset({"sales", "hr", "finance", "engineering"})


# 2. Truy vấn Mức quyền Tài liệu (visible_access_levels)
def visible_access_levels(role: str) -> list[str]:
    """Trả về danh sách mức quyền tài liệu được phép đọc; role lạ trả về rỗng (Fail-closed)."""
    return list(ROLE_VISIBLE_LEVELS.get(role, ()))


# 3. Phân quyền Số liệu Kinh doanh (SQL Department Boundary)
def can_query_department(*, role: str, caller_department: str, target_department: str) -> bool:
    """Kiểm tra quyền truy vấn SQL: employee/manager chỉ xem phòng mình, executive xem hết."""
    if role == "executive":
        return True
    if role in ("employee", "manager"):
        return caller_department == target_department
    return False


def can_compare_departments(*, role: str) -> bool:
    """Truy vấn so sánh doanh thu LIÊN phòng ban chỉ dành cho executive.

    Khác `can_query_department` (so một phòng ban cụ thể với phòng ban của người
    gọi): truy vấn so sánh trả về TẤT CẢ phòng ban trong cùng một lần, nên không có
    khái niệm "đúng phòng ban của mình" — hoặc được xem toàn bộ, hoặc không được xem
    gì. Một manager/employee dù đúng phòng ban vẫn không có lý do nghiệp vụ để thấy
    số liệu phòng ban khác chỉ vì đi kèm trong một bảng so sánh.
    """
    return role == "executive"
