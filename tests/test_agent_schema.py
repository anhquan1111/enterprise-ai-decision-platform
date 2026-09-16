"""Test cho src/agent/schema.py: hai lop validate cua ToolPlan."""

import pytest
from pydantic import ValidationError

from src.agent.schema import SqlArgs, ToolPlan


def test_docs_only_plan_is_valid() -> None:
    plan = ToolPlan.model_validate({"tools": ["docs"]})

    assert plan.tools == ["docs"]
    assert plan.sql_args is None


def test_sql_plan_with_args_is_valid() -> None:
    plan = ToolPlan.model_validate(
        {
            "tools": ["sql"],
            "sql_args": {
                "department": "sales",
                "month_from": "2026-01-01",
                "month_to": "2026-06-01",
            },
        }
    )

    assert plan.sql_args is not None
    assert plan.sql_args.department == "sales"


def test_sql_plan_missing_sql_args_is_rejected() -> None:
    """Đây là lớp validate thứ hai (nghiệp vụ giữa các trường), không phải lỗi hình
    dạng đơn thuần — ``model_validator(mode="after")`` bắt đúng ca này."""
    with pytest.raises(ValidationError):
        ToolPlan.model_validate({"tools": ["sql"]})


def test_unknown_department_literal_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SqlArgs(department="marketing", month_from="2026-01-01", month_to="2026-06-01")


def test_unknown_tool_name_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ToolPlan.model_validate({"tools": ["delete_everything"]})


def test_both_tools_is_valid() -> None:
    plan = ToolPlan.model_validate(
        {
            "tools": ["sql", "docs"],
            "sql_args": {
                "department": "finance",
                "month_from": "2026-01-01",
                "month_to": "2026-06-01",
            },
        }
    )

    assert plan.tools == ["sql", "docs"]


def test_single_department_defaults_query_type() -> None:
    """query_type mặc định phải là 'single_department' để không phá vỡ các lệnh gọi
    cũ chưa biết về loại truy vấn mới."""
    args = SqlArgs(department="sales", month_from="2026-01-01", month_to="2026-01-01")

    assert args.query_type == "single_department"


def test_compare_departments_does_not_require_department() -> None:
    args = SqlArgs(query_type="compare_departments", month_from="2026-01-01", month_to="2026-06-01")

    assert args.department is None


def test_single_department_without_department_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SqlArgs(query_type="single_department", month_from="2026-01-01", month_to="2026-06-01")


def test_unknown_query_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SqlArgs(query_type="delete_everything", month_from="2026-01-01", month_to="2026-06-01")
