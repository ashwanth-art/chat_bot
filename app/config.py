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
    mongodb_collection: str = "knowledge_chunks"
    mongodb_vector_index: str = "vector_index"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    top_k: int = Field(default=5, ge=1, le=20)
    max_context_chars: int = Field(default=12000, ge=1000, le=50000)
    allow_origins: str = "http://localhost:8000"
    log_level: str = "INFO"

    @property
    def origins(self) -> list[str]:
        return [item.strip() for item in self.allow_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
