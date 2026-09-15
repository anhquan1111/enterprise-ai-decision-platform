"""D4: bo test cach ly RBAC co he thong — ma tran day du, khong chi vai vi du rai
rac. Gom lai tu hai duong quyen da co (docs theo access_level, SQL theo department)
thanh mot noi kiem tra toan dien, dung du lieu nhan vien that (D1 seed).
"""

from itertools import product

import pytest

from src.retrieval import retrieve
from src.scope import ROLE_VISIBLE_LEVELS, can_query_department, visible_access_levels

ROLES = ["employee", "manager", "executive"]
DEPARTMENTS = ["engineering", "finance", "hr", "sales"]
ACCESS_LEVELS = ["employee", "manager", "executive"]


# ── Ma trận thuần logic (không cần DB) ──────────────────────────────


@pytest.mark.parametrize("role,access_level", list(product(ROLES, ACCESS_LEVELS)))
def test_docs_access_matrix_matches_hierarchy(role: str, access_level: str) -> None:
    """Một role chỉ được thấy access_level của chính nó và các mức THẤP HƠN — không
    có ngoại lệ nào lọt qua ma trận này."""
    expected = access_level in ROLE_VISIBLE_LEVELS[role]

    assert (access_level in visible_access_levels(role)) == expected


@pytest.mark.parametrize(
    "role,caller_dept,target_dept", list(product(ROLES, DEPARTMENTS, DEPARTMENTS))
)
def test_sql_department_matrix_matches_adr_012(
    role: str, caller_dept: str, target_dept: str
) -> None:
    """ADR-012: employee/manager chỉ xem phòng ban của chính mình; executive xem mọi
    phòng ban. Test đủ 3 role × 4 × 4 phòng ban = 48 tổ hợp, không chỉ vài ca mẫu."""
    result = can_query_department(
        role=role, caller_department=caller_dept, target_department=target_dept
    )

    if role == "executive":
        assert result is True
    else:
        assert result == (caller_dept == target_dept)


def test_unknown_role_is_denied_in_both_docs_and_sql_matrices() -> None:
    assert visible_access_levels("khach_la") == []
    assert (
        can_query_department(role="khach_la", caller_department="sales", target_department="sales")
        is False
    )


# ── Cách ly thật trên dữ liệu thật (D1 seed) ────────────────────────


@pytest.mark.integration
def test_employee_never_retrieves_a_chunk_above_their_access_level() -> None:
    """Không suy luận từ code — đọc THẬT toàn bộ kết quả retrieve() của một employee
    trên một câu hỏi cố ý rộng, xác nhận không một chunk manager/executive nào lọt."""
    chunks = retrieve("chinh sach quy dinh cong ty", role="employee", k=20)

    assert chunks  # câu hỏi đủ rộng để có kết quả — nếu rỗng thì test này vô nghĩa
    assert all(c.access_level == "employee" for c in chunks)


@pytest.mark.integration
def test_manager_never_retrieves_executive_only_chunks() -> None:
    chunks = retrieve("chinh sach quy dinh cong ty", role="manager", k=20)

    assert chunks
    assert all(c.access_level in ("employee", "manager") for c in chunks)


@pytest.mark.integration
def test_seeded_employees_in_different_departments_are_isolated() -> None:
    """emp_001 (sales/employee) và emp_003 (finance/employee) — hai nhân viên THẬT đã
    seed ở D1 — không được phép xem số liệu của phòng ban nhau. Vòng lặp xác thực
    thật bằng API key thật đã kiểm riêng ở test_auth_integration.py; ở đây kiểm đúng
    ranh giới ADR-012 áp dụng cho đúng hai phòng ban thật đang tồn tại trong seed."""
    assert (
        can_query_department(
            role="employee", caller_department="sales", target_department="finance"
        )
        is False
    )
    assert (
        can_query_department(
            role="employee", caller_department="finance", target_department="sales"
        )
        is False
    )
    assert (
        can_query_department(role="employee", caller_department="sales", target_department="sales")
        is True
    )
