"""Test cho scope.py: can_query_department, ranh gioi RBAC cho tool SQL (D3, ADR-012).

Tach rieng test_contracts.py vi visible_access_levels da co test o do cho duong docs;
day chi test them ranh gioi moi cho duong SQL.
"""

from src.scope import can_query_department


def test_employee_can_query_own_department() -> None:
    assert can_query_department(
        role="employee", caller_department="sales", target_department="sales"
    )


def test_employee_cannot_query_other_department() -> None:
    assert not can_query_department(
        role="employee", caller_department="sales", target_department="finance"
    )


def test_manager_cannot_query_other_department() -> None:
    """Manager không có ưu tiên cao hơn employee ở ranh giới này — chỉ executive mới
    xem được liên phòng ban (ADR-012)."""
    assert not can_query_department(
        role="manager", caller_department="engineering", target_department="sales"
    )


def test_executive_can_query_any_department() -> None:
    assert can_query_department(
        role="executive", caller_department="hr", target_department="finance"
    )


def test_unknown_role_is_denied_not_guessed() -> None:
    assert not can_query_department(
        role="ceo_of_everything", caller_department="sales", target_department="sales"
    )
