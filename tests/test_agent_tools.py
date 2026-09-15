"""Test cho src/agent/tools.py: RBAC kiem TRUOC khi cau SQL chay, loi nghiep vu khong
lam sap he thong. Mock fetch_all/retrieve — khong cham database hay Gemini that."""

import pytest

from src.agent import tools as tools_module
from src.agent.schema import SqlArgs
from src.agent.tools import ToolExecutionError, ToolPermissionError, sql_tool


def make_row(month: str = "2026-01-01", revenue: int = 1_000_000, is_final: bool = True) -> dict:
    import datetime

    return {
        "month": datetime.date.fromisoformat(month),
        "revenue_vnd": revenue,
        "is_final": is_final,
    }


def test_employee_can_query_own_department(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools_module, "fetch_all", lambda *a, **kw: [make_row()])
    args = SqlArgs(department="sales", month_from="2026-01-01", month_to="2026-01-01")

    text, rows = sql_tool(args, role="employee", caller_department="sales")

    assert "1.000.000 VND" in text or "1,000,000 VND" in text
    assert len(rows) == 1


def test_employee_is_blocked_from_other_department_before_query_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RBAC chặn PHẢI xảy ra trước khi fetch_all được gọi — nếu không, dữ liệu đã bị
    database trả về trước khi quyết định có được xem hay không."""
    called = {"count": 0}

    def spy_fetch_all(*a: object, **kw: object) -> list[dict]:
        called["count"] += 1
        return [make_row()]

    monkeypatch.setattr(tools_module, "fetch_all", spy_fetch_all)
    args = SqlArgs(department="finance", month_from="2026-01-01", month_to="2026-01-01")

    with pytest.raises(ToolPermissionError):
        sql_tool(args, role="employee", caller_department="sales")

    assert called["count"] == 0


def test_executive_can_query_any_department(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools_module, "fetch_all", lambda *a, **kw: [make_row()])
    args = SqlArgs(department="finance", month_from="2026-01-01", month_to="2026-01-01")

    text, _rows = sql_tool(args, role="executive", caller_department="sales")

    assert text  # không bị chặn, kể cả khác department với người gọi


def test_no_data_raises_business_error_not_permission_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tools_module, "fetch_all", lambda *a, **kw: [])
    args = SqlArgs(department="sales", month_from="2026-01-01", month_to="2026-01-01")

    with pytest.raises(ToolExecutionError):
        sql_tool(args, role="executive", caller_department="sales")


def test_tentative_month_is_labeled_in_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools_module, "fetch_all", lambda *a, **kw: [make_row(is_final=False)])
    args = SqlArgs(department="sales", month_from="2026-06-01", month_to="2026-06-01")

    text, _rows = sql_tool(args, role="executive", caller_department="sales")

    assert "tạm tính" in text
