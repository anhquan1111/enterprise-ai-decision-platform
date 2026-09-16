"""Test cho src/agent/tools.py: RBAC kiem TRUOC khi cau SQL chay, loi nghiep vu khong
lam sap he thong. Mock fetch_all/retrieve — khong cham database hay Gemini that."""

from pathlib import Path

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


def test_growth_percentage_is_surfaced_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """mom_growth_pct đã được SQL tính sẵn bằng window function — trước đây bị bỏ phí,
    không hiện trong câu trả lời. Giờ phải xuất hiện."""
    row = make_row()
    row["mom_growth_pct"] = 12.5
    monkeypatch.setattr(tools_module, "fetch_all", lambda *a, **kw: [row])
    args = SqlArgs(department="sales", month_from="2026-01-01", month_to="2026-01-01")

    text, _rows = sql_tool(args, role="executive", caller_department="sales")

    assert "+12.5%" in text


def test_negative_growth_percentage_keeps_minus_sign(monkeypatch: pytest.MonkeyPatch) -> None:
    row = make_row()
    row["mom_growth_pct"] = -8.0
    monkeypatch.setattr(tools_module, "fetch_all", lambda *a, **kw: [row])
    args = SqlArgs(department="sales", month_from="2026-01-01", month_to="2026-01-01")

    text, _rows = sql_tool(args, role="executive", caller_department="sales")

    assert "-8.0%" in text
    assert "+-8.0%" not in text


def test_executive_can_compare_departments(monkeypatch: pytest.MonkeyPatch) -> None:
    row = {**make_row(), "department": "sales", "full_name": "Khối Kinh doanh"}
    monkeypatch.setattr(tools_module, "fetch_all", lambda *a, **kw: [row])
    args = SqlArgs(query_type="compare_departments", month_from="2026-01-01", month_to="2026-01-01")

    text, rows = sql_tool(args, role="executive", caller_department="finance")

    assert "Khối Kinh doanh" in text
    assert len(rows) == 1


def test_employee_cannot_compare_departments(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"count": 0}

    def spy_fetch_all(*a: object, **kw: object) -> list[dict]:
        called["count"] += 1
        return []

    monkeypatch.setattr(tools_module, "fetch_all", spy_fetch_all)
    args = SqlArgs(query_type="compare_departments", month_from="2026-01-01", month_to="2026-01-01")

    with pytest.raises(ToolPermissionError):
        sql_tool(args, role="employee", caller_department="sales")

    assert called["count"] == 0


def test_manager_cannot_compare_departments(monkeypatch: pytest.MonkeyPatch) -> None:
    args = SqlArgs(query_type="compare_departments", month_from="2026-01-01", month_to="2026-01-01")

    with pytest.raises(ToolPermissionError):
        sql_tool(args, role="manager", caller_department="finance")


def test_no_sql_file_has_a_stray_percent_outside_real_placeholders() -> None:
    """ADR-030: psycopg quét TOÀN BỘ văn bản câu lệnh (kể cả bên trong comment) để
    tìm token cần bind — một ký tự phần trăm "mồ côi" trong comment từng làm
    08_business_metrics_compare.sql ném ProgrammingError lúc chạy thật, dù mọi unit
    test mock fetch_all đều xanh (mock không đi qua psycopg nên không bắt được lớp
    lỗi này). Kiểm tĩnh, chạy mặc định, không cần DB — bắt ngay lần sau ai thêm một
    comment kiểu vậy, không phải đợi tới khi gọi API thật mới lộ ra 500.

    Chỉ kiểm hai file THẬT SỰ đi qua psycopg.execute() bằng tham số (`src/agent/tools.py`)
    — các file schema/seed khác chạy bằng `psql -f` trực tiếp, không qua client-side
    parameter binding của psycopg, nên `%` ở đó (nếu có) không phải cùng một lớp rủi ro.
    """
    sql_dir = Path(__file__).parent.parent / "sql"
    real_placeholders = ("%(department)s", "%(month_from)s", "%(month_to)s")
    parameterized_files = ("03_business_metrics.sql", "08_business_metrics_compare.sql")

    for name in parameterized_files:
        text = (sql_dir / name).read_text(encoding="utf-8")
        for placeholder in real_placeholders:
            text = text.replace(placeholder, "")
        assert "%" not in text, f"{name} có ký tự % ngoài placeholder hợp lệ"
