"""Application configuration.

Single source of truth for runtime settings, loaded from environment / .env.
Access via :func:`get_settings` (cached) so the whole app shares one instance.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed, validated application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- Core ----
    app_name: str = "AI IT Helpdesk Agent"
    environment: str = "development"
    log_level: str = "INFO"
    log_json: bool = False

    # ---- Database ----
    database_url: str = "sqlite+aiosqlite:///./helpdesk.db"
    db_echo: bool = False

    # ---- Anthropic / LLM ----
    anthropic_api_key: SecretStr = Field(
        default=SecretStr(""), validation_alias="ANTHROPIC_API_KEY"
    )
    anthropic_base_url: str | None = None
    llm_model: str = "claude-sonnet-4-6"
    llm_max_tokens: int = 4096
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 4
    llm_enable_prompt_cache: bool = True
    llm_thinking_enabled: bool = False
    llm_thinking_budget_tokens: int = 2048

    # ---- Agent loop budgets ----
    agent_max_steps: int = 12
    agent_max_attempts: int = 3
    agent_max_replans: int = 2
    agent_cost_ceiling_cents: float = 50.0

    # ---- Confidence gate ----
    confidence_auto_threshold: float = 0.85
    confidence_verify_threshold: float = 0.70

    # ---- RAG ----
    rag_top_k: int = 4
    rag_dense_k: int = 20
    rag_keyword_k: int = 20
    rag_score_floor: float = 0.30
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    chroma_path: str = "./chroma_db"
    chroma_collection: str = "kb_articles"

    # ---- Follow-up scheduler ----
    followup_delay_seconds: int = 7200
    scheduler_poll_seconds: int = 5
    followup_no_response_timeout_seconds: int = 86400

    # ---- Identity / OTP ----
    otp_ttl_seconds: int = 300
    otp_demo_code: str | None = None
    # Server-side secret that keys the OTP HMAC so a leaked code_hash column can't
    # be brute-forced offline. MUST be overridden via env in any real deployment.
    otp_secret: SecretStr = Field(
        default=SecretStr("dev-insecure-otp-secret"), validation_alias="OTP_SECRET"
    )

    # ---- HITL approval ----
    approval_timeout_seconds: int = 900

    # ---- CORS ----
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
    ]

    @field_validator("cors_origins")
    @classmethod
    def _reject_wildcard_origin(cls, v: list[str]) -> list[str]:
        # We send credentialed CORS requests; a "*" origin is both rejected by
        # browsers and a security footgun, so fail fast on misconfiguration.
        if "*" in v:
            raise ValueError(
                "cors_origins must not contain '*' (credentialed CORS requires "
                "explicit origins). List each allowed origin instead."
            )
        return v

    @property
    def llm_configured(self) -> bool:
        """True when a usable Anthropic credential is present."""
        return bool(self.anthropic_api_key.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings singleton."""
    return Settings()
