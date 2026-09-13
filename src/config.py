"""Cấu hình ứng dụng, đọc từ biến môi trường và .env.

Mọi setting có giá trị mặc định cho môi trường local nên app chạy được khi chưa có
.env. Riêng secret (LLM_API_KEY) mặc định là rỗng chứ không phải một giá trị giả:
thiếu key thì phải lỗi rõ ràng, không phải lỗi auth khó hiểu.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Setting dùng chung cho API và các script offline."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── App ───────────────────────────────────────────────
    app_name: str = "enterprise-ai-decision-platform"
    app_version: str = "0.1.0"
    environment: str = "local"
    log_level: str = "INFO"

    # ── PostgreSQL ─────────────────────────────────────────
    # Dùng 127.0.0.1 chứ không phải "localhost": trên Windows localhost resolve ::1
    # trước, mà compose chỉ publish port trên IPv4, nên mỗi connection phải trả giá
    # cho một lần thử IPv6 thất bại. Xem ADR-005.
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5433
    postgres_db: str = "enterprise_ai"
    postgres_user: str = "app"
    postgres_password: str = "app_local_only"
    # Số giây libpq chờ cho MỖI địa chỉ đã resolve. Thiếu tham số này thì mặc định
    # là chờ vô hạn, biến "database không tới được" thành treo thay vì lỗi. ADR-005.
    postgres_connect_timeout: int = 5

    # ── LLM: đã chốt ở ADR-002 ────────────────────────────
    llm_provider: str = "google"
    # Pin phiên bản cụ thể, KHÔNG dùng alias "-latest": alias đổi model dưới chân bạn
    # và làm mọi số đo cũ không so được với số mới.
    llm_model: str = "gemini-3.1-flash-lite"
    llm_api_key: str = ""

    # ── Embedding: đã chốt ở ADR-002 ──────────────────────
    embedding_backend: str = "api"
    embedding_model: str = "gemini-embedding-001"
    # 384 chiều là do Matryoshka truncation (outputDimensionality), không phải chiều
    # gốc của model — gốc là 3072. Chọn 384 để giữ nguyên cột vector(384) của schema.
    embedding_dim: int = 384

    # Gemini 3.x bật "thinking" mặc định và thinking token TRỪ VÀO max_output_tokens.
    # Đặt quá thấp thì response rỗng với finishReason=MAX_TOKENS. Xem ADR-002.
    llm_max_output_tokens: int = 1200

    # ── Retrieval ──────────────────────────────────────────
    retrieval_top_k: int = 5
    # Hằng số của Reciprocal Rank Fusion: score = sum(1 / (rrf_k + rank)).
    # 60 là giá trị trong paper gốc, làm dịu trọng số của các hạng đầu để một
    # engine không áp đảo danh sách sau khi trộn.
    rrf_k: int = 60

    @property
    def database_url(self) -> str:
        """Connection string cho psycopg.

        Luôn kèm connect_timeout: database không tới được phải lỗi trong thời gian
        có giới hạn, không được chặn caller vô hạn.
        """
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
            f"?connect_timeout={self.postgres_connect_timeout}"
        )


@lru_cache
def get_settings() -> Settings:
    """Trả về object setting dùng chung cho cả process.

    Cache lại để mỗi module import không phải đọc lại environment. Test muốn đổi
    biến môi trường thì gọi ``get_settings.cache_clear()``.
    """
    return Settings()
