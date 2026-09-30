"""Application settings, loaded from environment variables or a `.env` file."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- LLM ---
    openai_api_key: str | None = Field(default=None, description="OpenAI (or compatible) API key")
    openai_base_url: str | None = Field(
        default=None, description="Custom base URL for OpenAI-compatible providers (Azure, Ollama, OpenRouter...)"
    )
    llm_model: str = Field(default="gpt-4.1-mini", description="Vision-capable chat model")
    llm_temperature: float | None = Field(default=0.0, ge=0.0, le=2.0)
    llm_max_output_tokens: int = Field(default=4000, ge=256)
    llm_max_retries: int = Field(default=2, ge=0, le=10)
    request_timeout: int = Field(default=120, ge=10, le=600)

    # --- Documents ---
    max_file_size_mb: int = Field(default=15, gt=0, le=200)
    max_pages: int = Field(default=5, ge=1, le=50, description="Max pages sent to the model per document")
    max_text_chars: int = Field(default=40_000, ge=1_000)
    image_max_side: int = Field(default=2000, ge=512, le=4096, description="Images are downscaled to this size")

    # --- Storage / server ---
    database_path: str = Field(default="./data/invoices.db")
    cors_origins: str = Field(default="*", description="Comma-separated list of allowed origins")
    log_level: str = Field(default="INFO")

    @field_validator("llm_temperature", mode="before")
    @classmethod
    def empty_temperature(cls, v):
        # Allow `LLM_TEMPERATURE=` to omit the parameter (needed for reasoning models).
        return None if v in ("", None) else v

    @field_validator("log_level")
    @classmethod
    def upper_log_level(cls, v: str) -> str:
        return v.upper()

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def llm_configured(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def db_file(self) -> Path:
        return Path(self.database_path)


@lru_cache
def get_settings() -> Settings:
    return Settings()
