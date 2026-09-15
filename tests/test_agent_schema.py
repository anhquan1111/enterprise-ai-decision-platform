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
