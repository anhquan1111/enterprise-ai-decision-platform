"""Phạm vi quyền truy cập — thuần logic, không phụ thuộc thư viện nặng.

Tách riêng khỏi ``src/contracts.py`` có lý do cụ thể: contracts import pandas để
validate batch ingestion, nhưng đường serving chỉ cần tra một dict. Để chung thì mọi
nơi dùng phạm vi quyền đều phải kéo theo pandas và numpy — đã gặp thật: script
benchmark chết vì OpenBLAS không cấp được bộ nhớ, trong khi nó không cần pandas.

Module này là nguồn sự thật duy nhất về "role nào đọc được mức nào", dùng chung cho cả
ingestion và truy vấn. Hai bản sao của quy tắc quyền là cách sinh lỗi cách ly dữ liệu.
"""

# Thứ bậc quyền: một role đọc được mức của chính nó và mọi mức thấp hơn.
ROLE_VISIBLE_LEVELS: dict[str, tuple[str, ...]] = {
    "employee": ("employee",),
    "manager": ("employee", "manager"),
    "executive": ("employee", "manager", "executive"),
}

ALLOWED_ACCESS_LEVELS: frozenset[str] = frozenset({"employee", "manager", "executive"})
ALLOWED_DEPARTMENTS: frozenset[str] = frozenset({"sales", "hr", "finance", "engineering"})


def visible_access_levels(role: str) -> list[str]:
    """Các mức quyền mà một role được đọc.

    Role lạ trả về danh sách rỗng thay vì mức thấp nhất: không biết người gọi là ai thì
    không cho thấy gì, chứ không đoán.
    """
    return list(ROLE_VISIBLE_LEVELS.get(role, ()))
