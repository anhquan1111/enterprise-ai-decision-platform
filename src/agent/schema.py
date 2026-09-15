"""Schema cho quyet dinh cua router: tool nao can goi, voi tham so gi.

Ap dung dung co che da hoc va do o Ngay 22 (Agent_Loop_&_Tool_Use): validate theo hai
lop tach biet — hinh dang chung cua ToolPlan, roi hinh dang tham so rieng theo tung
tool duoc chon. Tool "docs" khong can tham so rieng vi cau hoi goc da du de retrieval.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class SqlArgs(BaseModel):
    """Tham so cho tool SQL. `department` la muc tieu cau truy van, KHONG phai
    department cua nguoi hoi — hai gia tri co the khac nhau, va chinh su khac nhau do
    la dieu RBAC (scope.can_query_department) phai kiem truoc khi thuc thi."""

    department: Literal["engineering", "finance", "hr", "sales"]
    month_from: str = Field(description="YYYY-MM-01, dau thang bat dau")
    month_to: str = Field(description="YYYY-MM-01, dau thang ket thuc")


class ToolPlan(BaseModel):
    """Quyet dinh cua router cho MOT lan hoi: tool nao can goi.

    `tools` co the la ["docs"], ["sql"], hoac ["sql", "docs"] khi cau hoi can ca hai
    (vi du: "so sanh doanh thu thang nay voi quy dinh muc tieu doanh thu"). `sql_args`
    chi bat buoc khi "sql" nam trong `tools`.
    """

    tools: list[Literal["sql", "docs"]] = Field(min_length=1, max_length=2)
    sql_args: SqlArgs | None = None

    @model_validator(mode="after")
    def sql_tool_requires_sql_args(self) -> "ToolPlan":
        if "sql" in self.tools and self.sql_args is None:
            raise ValueError("tools chứa 'sql' nhưng thiếu sql_args")
        return self
