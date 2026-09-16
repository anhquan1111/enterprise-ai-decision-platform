"""Khế ước dữ liệu cho quyết định của Agent Router: chọn công cụ và tham số tương ứng.

Xác thực hai lớp: hình dạng tổng thể của ToolPlan và tính toàn vẹn tham số của từng tool.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

# 1. Tham Số Truy Vấn Số Liệu Kinh Doanh (SqlArgs)


class SqlArgs(BaseModel):
    """Tham số phục vụ công cụ truy vấn SQL số liệu doanh thu hàng tháng.

    `department` là mục tiêu truy vấn do LLM đề xuất từ câu hỏi, KHÔNG PHẢI phòng ban thật
    của người gọi. Điểm sai khác này bắt buộc phải được RBAC kiểm duyệt trước khi chạy SQL.

    `query_type` chọn MỘT trong hai câu SQL cố định đã có sẵn (không có "câu SQL tự do
    thứ ba" nào khác) — mở rộng số loại câu hỏi trả lời được vẫn không đổi nguyên tắc
    ADR-013: không bao giờ để LLM tự sinh SQL.
    - "single_department": doanh thu MỘT phòng ban theo tháng (bắt buộc có `department`).
    - "compare_departments": so sánh doanh thu MỌI phòng ban trong cùng khoảng thời gian
      (bỏ qua `department` nếu có — chỉ executive được dùng, xem scope.can_compare_departments).
    """

    query_type: Literal["single_department", "compare_departments"] = "single_department"
    department: Literal["engineering", "finance", "hr", "sales"] | None = None
    month_from: str = Field(description="YYYY-MM-01, đầu tháng bắt đầu")
    month_to: str = Field(description="YYYY-MM-01, đầu tháng kết thúc")

    @model_validator(mode="after")
    def single_department_requires_department(self) -> "SqlArgs":
        """`department` chỉ thật sự bắt buộc khi hỏi về MỘT phòng ban cụ thể — hỏi so
        sánh mọi phòng ban thì không cần, và không nên bắt LLM điền một giá trị vô nghĩa."""
        if self.query_type == "single_department" and self.department is None:
            raise ValueError("query_type='single_department' nhưng thiếu department")
        return self


# 2. Kế Hoạch Điều Phối Công Cụ (ToolPlan)


class ToolPlan(BaseModel):
    """Kế hoạch lựa chọn công cụ của Agent Router cho một lượt câu hỏi.

    `tools` có thể là ['docs'], ['sql'], hoặc ['sql', 'docs'] khi câu hỏi cần kết hợp cả hai.
    Tool 'docs' không cần tham số riêng vì câu hỏi gốc được dùng trực tiếp để tìm kiếm vector.
    """

    tools: list[Literal["sql", "docs"]] = Field(min_length=1, max_length=2)
    sql_args: SqlArgs | None = None

    @model_validator(mode="after")
    def sql_tool_requires_sql_args(self) -> "ToolPlan":
        """Ràng buộc phụ thuộc chéo: router chọn 'sql' thì bắt buộc phải có `sql_args` đi kèm."""
        if "sql" in self.tools and self.sql_args is None:
            raise ValueError("tools chứa 'sql' nhưng thiếu sql_args")
        return self
