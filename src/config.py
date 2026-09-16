"""Cấu hình ứng dụng tập trung (Single Source of Truth), nạp từ biến môi trường và file .env."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Setting dùng chung cho FastAPI server, scripts và database migrations."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── 1. App Metadata ──────────────────────────────────
    app_name: str = "enterprise-ai-decision-platform"  # Tên hiển thị trên Swagger UI (/docs)
    app_version: str = "0.1.0"
    environment: str = "local"
    log_level: str = "INFO"

    # ── 2. PostgreSQL & Connection Pool ──────────────────
    # Dùng 127.0.0.1 thay vì localhost để tránh bị phạt 5s timeout IPv6 trên Windows (ADR-005)
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5433  # Cổng 5433 để tránh trùng cổng Postgres mặc định (5432)
    postgres_db: str = "enterprise_ai"
    postgres_user: str = "app"
    postgres_password: str = "app_local_only"
    # Timeout khi MỞ kết nối: tối đa 5s, tránh ứng dụng bị treo vô hạn nếu DB sập
    postgres_connect_timeout: int = 5
    # Timeout khi CHẠY câu SQL: server tự hủy câu lệnh nếu chạy quá 5s để chống treo DB
    postgres_statement_timeout_ms: int = 5000
    # Connection Pool: tối thiểu 1 kết nối sẵn sàng, tối đa 10 kết nối đồng thời để chống quá tải DB
    postgres_pool_min_size: int = 1
    postgres_pool_max_size: int = 10

    # ── 3. LLM (Gemini) ──────────────────────────────────
    llm_provider: str = "google"
    # Cố định phiên bản, không dùng alias "-latest" để kết quả đo đạc luôn nhất quán (ADR-002)
    llm_model: str = "gemini-3.1-flash-lite"
    llm_api_key: str = ""  # Mặc định rỗng để fail-fast, bắt buộc nạp từ .env

    # ── 4. Embedding ─────────────────────────────────────
    embedding_backend: str = "api"
    embedding_model: str = "gemini-embedding-001"
    # Cắt vector từ 3072D gốc xuống 384D (Matryoshka) để tối ưu tốc độ và dung lượng pgvector
    embedding_dim: int = 384

    # Ngân sách token đầu ra (Gemini 3.x trừ cả thinking tokens vào đây, ~400-600 từ tiếng Việt)
    llm_max_output_tokens: int = 1200

    # ── 5. Retrieval ──────────────────────────────────────
    retrieval_top_k: int = 5  # Lấy top 5 chunk tài liệu tương đồng nhất
    rrf_k: int = 60  # Hằng số làm mượt của RRF, dự phòng khi kích hoạt Hybrid Search

    # ── 6. JWT Authentication ────────────────────────────
    jwt_secret_key: str = ""  # Khóa bí mật dùng để ký token HS256 (bắt buộc nạp từ .env)
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 60  # Thời gian sống của vé JWT (hết hạn sau 60 phút)

    @property
    def database_url(self) -> str:
        """Tự động ráp thành Connection URI chuẩn, luôn kèm connect_timeout
        và statement_timeout.
        """
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
            f"?connect_timeout={self.postgres_connect_timeout}"
            f"&options=-c%20statement_timeout%3D{self.postgres_statement_timeout_ms}"
        )


@lru_cache
def get_settings() -> Settings:
    """Singleton cache: chỉ đọc và parse .env đúng một lần khi khởi động để tối ưu hiệu năng."""
    return Settings()
