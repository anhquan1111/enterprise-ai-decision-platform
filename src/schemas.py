"""Contract request/response của endpoint /ask.

Đây là biên của hệ thống. Hai thứ được tách riêng có chủ ý:

* **Schema hợp lệ** — Pydantic kiểm (hình dạng, kiểu, tập giá trị cho phép).
* **Nội dung đúng** — KHÔNG kiểm ở đây. Một response có thể đúng schema mà vẫn trả
  lời sai; đó là việc của bộ đánh giá ở giai đoạn retrieval nền tảng.
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class Role(StrEnum):
    """Vai trò của người gọi. Quyết định dòng dữ liệu và tài liệu nào được thấy."""

    EMPLOYEE = "employee"
    MANAGER = "manager"
    EXECUTIVE = "executive"


class Department(StrEnum):
    """Phòng ban của người gọi."""

    SALES = "sales"
    HR = "hr"
    FINANCE = "finance"
    ENGINEERING = "engineering"


class ToolUsed(StrEnum):
    """Nguồn bằng chứng của câu trả lời."""

    SQL = "sql"
    DOCS = "docs"
    BOTH = "both"
    NONE = "none"


class AskRequest(BaseModel):
    """Câu hỏi kèm danh tính người gọi.

    Role và department nằm trong request chứ không suy ra về sau, vì mọi truy cập
    dữ liệu phía dưới đều bị giới hạn theo hai trường này.
    """

    user_id: str = Field(min_length=1, max_length=64, examples=["emp_042"])
    role: Role
    department: Department
    question: str = Field(min_length=3, max_length=2000)


class Citation(BaseModel):
    """Một bằng chứng cho một khẳng định trong câu trả lời.

    Citation phải trỏ tới thứ truy lại được: một chunk tài liệu, hoặc chính câu SQL
    đã tạo ra con số. Không có nó thì câu trả lời không kiểm chứng được, và câu trả
    lời không kiểm chứng được bị coi là thất bại.
    """

    source_type: ToolUsed
    # Citation tài liệu điền doc_id/chunk_index/quote; citation số liệu điền sql.
    doc_id: str | None = None
    chunk_index: int | None = None
    quote: str | None = None
    sql: str | None = None


class AskResponse(BaseModel):
    """Câu trả lời có cấu trúc trả về cho người gọi."""

    request_id: str
    answer: str
    citations: list[Citation]
    tool_used: ToolUsed
    # True khi hệ thống từ chối trả lời vì bằng chứng trong phạm vi quyền không đủ.
    # Từ chối là kết quả đúng, không phải lỗi.
    abstained: bool
    latency_ms: int


class HealthResponse(BaseModel):
    """Liveness: process còn sống. Không nói gì về dependency."""

    status: str
    app: str
    version: str
    environment: str


class ReadyResponse(BaseModel):
    """Readiness: process thật sự phục vụ được request."""

    ready: bool
    checks: dict[str, str]


class TokenResponse(BaseModel):
    """Kết quả của POST /auth/token — đổi một API key hợp lệ lấy một JWT ngắn hạn.

    Đặt tên field theo đúng quy ước OAuth2 (``access_token``/``token_type``/
    ``expires_in``, RFC 6749 §5.1) dù đây không phải OAuth2 đầy đủ — quy ước quen
    thuộc, không cần bịa tên field riêng.
    """

    access_token: str
    token_type: str = "bearer"
    expires_in: int
