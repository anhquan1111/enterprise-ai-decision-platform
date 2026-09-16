"""Hợp đồng dữ liệu (Data Contracts) Pydantic cho Request/Response của API."""

from enum import StrEnum

from pydantic import BaseModel, Field


# ── 1. Danh mục nghiệp vụ (Enums) ──────────────────────
class Role(StrEnum):
    """Vai trò người dùng, quyết định phạm vi tài liệu và số liệu được phép truy cập."""

    EMPLOYEE = "employee"
    MANAGER = "manager"
    EXECUTIVE = "executive"


class Department(StrEnum):
    """Phòng ban của người gọi, dùng để phân quyền truy vấn số liệu kinh doanh."""

    SALES = "sales"
    HR = "hr"
    FINANCE = "finance"
    ENGINEERING = "engineering"


class ToolUsed(StrEnum):
    """Nguồn bằng chứng được hệ thống sử dụng để trả lời."""

    SQL = "sql"
    DOCS = "docs"
    BOTH = "both"
    NONE = "none"


# ── 2. Hợp đồng hỏi đáp (/ask) ────────────────────────
class AskRequest(BaseModel):
    """Dữ liệu câu hỏi kèm danh tính người gọi gửi lên API /ask."""

    user_id: str = Field(min_length=1, max_length=64, examples=["emp_042"])
    role: Role
    department: Department
    question: str = Field(min_length=3, max_length=2000)


class Citation(BaseModel):
    """Bằng chứng trích dẫn cụ thể chứng minh cho câu trả lời."""

    source_type: ToolUsed
    # Nếu là tài liệu: điền doc_id, chunk_index và đoạn trích dẫn nguyên văn (quote)
    doc_id: str | None = None
    chunk_index: int | None = None
    quote: str | None = None  # Đoạn trích nguyên văn từ tài liệu gốc làm bằng chứng đối chiếu
    # Nếu là số liệu kinh doanh: điền câu lệnh SQL đã chạy sinh ra con số
    sql: str | None = None


class AskResponse(BaseModel):
    """Câu trả lời hoàn chỉnh có cấu trúc trả về cho người dùng."""

    # Mã UUIDv4 sinh ngẫu nhiên khi request chạm vào API, dùng truy vết và tra cứu audit_log
    request_id: str
    answer: str
    citations: list[Citation]
    tool_used: ToolUsed
    # Trả về True nếu hệ thống từ chối trả lời (do ngoài quyền hạn hoặc không có dữ liệu đối chiếu)
    abstained: bool
    latency_ms: int


# ── 3. Hợp đồng hệ thống & Xác thực ───────────────────
class HealthResponse(BaseModel):
    """Liveness probe: kiểm tra tiến trình server còn sống (/health)."""

    status: str
    app: str
    version: str
    environment: str


class ReadyResponse(BaseModel):
    """Readiness probe: kiểm tra server đã kết nối DB và sẵn sàng phục vụ (/ready)."""

    ready: bool
    checks: dict[str, str]


class TokenResponse(BaseModel):
    """Khuôn mẫu dữ liệu trả về khi đăng nhập thành công tại POST /auth/token.

    Theo chuẩn OAuth2 (RFC 6749): Trả về vé JWT ngắn hạn để client dùng cho các request sau.
    """

    access_token: str  # Chuỗi vé JWT đã được server ký số bằng secret key
    token_type: str = "bearer"  # Loại token theo chuẩn RFC 6750 (người cầm vé có quyền truy cập)
    expires_in: int  # Thời gian sống của vé tính bằng giây (ví dụ 3600 = 60 phút)
