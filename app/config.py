from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    chatbot_api_key: str = Field(min_length=12)
    cloud_audit_api_key: str = Field(min_length=12)
    monitoring_api_key: str = Field(min_length=12)
    openai_api_key: str = Field(min_length=20)
    openai_model: str = "gpt-5.6-sol"
    openai_reasoning_effort: str = "low"
    mongodb_uri: str = Field(min_length=20)
    mongodb_database: str = "aci_chatbot"
    aci_collection: str = "aci_openai_chunks"
    aci_vector_index: str = "openai_vector_index"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_embedding_dimensions: int = Field(default=1536, ge=1)
    top_k: int = Field(default=5, ge=1, le=20)
    max_context_chars: int = Field(default=12000, ge=1000, le=50000)
    allow_origins: str = "http://localhost:8000"
    log_level: str = "INFO"

    # --- request limits and cost control -------------------------------------
    rate_limit_enabled: bool = True
    rate_limit_requests_per_minute: int = Field(default=30, ge=1, le=6000)
    rate_limit_burst: int = Field(default=10, ge=1, le=1000)
    daily_token_budget: int = Field(default=200_000, ge=1000)
    request_timeout_seconds: float = Field(default=45.0, ge=1.0, le=300.0)

    # --- declared service levels, judged by the assessor ---------------------
    slo_p95_latency_ms: int = Field(default=3000, ge=100)
    slo_error_rate: float = Field(default=0.02, ge=0.0, le=1.0)

    # --- retention -----------------------------------------------------------
    trace_retention_seconds: int = Field(default=3600, ge=60)
    record_retention_days: int | None = None

    @property
    def origins(self) -> list[str]:
        return [item.strip() for item in self.allow_origins.split(",") if item.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() in {"production", "prod"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
