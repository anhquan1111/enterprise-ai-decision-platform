"""Application configuration, loaded from environment variables and .env.

Every setting has a local-development default so the app starts without a .env
file. Secrets (LLM_API_KEY) default to empty rather than to a placeholder value,
so a missing key fails loudly instead of producing confusing auth errors.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the API and the offline scripts."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── App ────────────────────────────────────────────────
    app_name: str = "enterprise-ai-decision-platform"
    app_version: str = "0.1.0"
    environment: str = "local"
    log_level: str = "INFO"

    # ── PostgreSQL ─────────────────────────────────────────
    # 127.0.0.1, not "localhost": on Windows "localhost" resolves to ::1 first and
    # compose binds the port on 127.0.0.1 only, so the v6 attempt stalls the
    # connection. See docs/decisions.md ADR-005.
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5433
    postgres_db: str = "enterprise_ai"
    postgres_user: str = "app"
    postgres_password: str = "app_local_only"

    # ── LLM (chosen on D2 — see docs/decisions.md ADR-002) ──
    llm_provider: str = "unset"
    llm_model: str = "unset"
    llm_api_key: str = ""

    # ── Embeddings (chosen on D2) ──────────────────────────
    embedding_backend: str = "local"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384

    # ── Retrieval ──────────────────────────────────────────
    retrieval_top_k: int = 5
    # Reciprocal Rank Fusion constant: score = sum(1 / (rrf_k + rank)).
    # 60 is the value from the original RRF paper; it damps the weight of
    # top ranks so one engine cannot dominate the fused list.
    rrf_k: int = 60

    @property
    def database_url(self) -> str:
        """libpq connection string for psycopg."""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings object.

    Cached so that importing modules do not each re-read the environment, and so
    tests can clear the cache with ``get_settings.cache_clear()`` after patching
    environment variables.
    """
    return Settings()
