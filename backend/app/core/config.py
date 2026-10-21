from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_JWT_SECRETS = {"change_me", "changeme", "secret", ""}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Mock HRMS API"
    environment: str = "dev"
    app_timezone: str = "Asia/Kolkata"
    database_url: str = "sqlite+aiosqlite:///./storage/hrms.db"
    cors_origins: str = "http://localhost:3000"

    jwt_secret_key: str = "change_me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    policy_upload_dir: str = "./storage/hr-policies"
    profile_photo_upload_dir: str = "./storage/profile-photos"
    employee_document_upload_dir: str = "./storage/employee-documents"

    # --- AI Copilot ---
    # The copilot works without an API key (deterministic rule-based engines);
    # with a key, Claude is used for intent classification, SQL generation,
    # action extraction and grounded answer generation.
    anthropic_api_key: str | None = None
    ai_llm_enabled: bool = True
    ai_model: str = "claude-opus-5-5"
    ai_effort: str = "low"
    ai_llm_timeout_seconds: float = 30.0
    ai_refusal_fallback: bool = True
    # Base URL the action agent uses to call this backend's own APIs.
    ai_internal_api_base_url: str = "http://127.0.0.1:8000"
    ai_sql_max_rows: int = 100
    ai_sql_timeout_seconds: float = 5.0
    ai_embedding_backend: str = "hashing"
    ai_rag_top_k: int = 4
    ai_rag_min_score: float = 0.05
    # With an LLM, questions whose best match scores below this are rewritten into policy terms and re-searched.
    ai_rag_rewrite_below_score: float = 0.15
    ai_rate_limit_per_minute: int = 30
    ai_confirmation_ttl_seconds: int = 300

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"prod", "production"}

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def validate_for_runtime(self) -> None:
        """Fail fast on configuration that must never reach production."""
        if self.is_production and (self.jwt_secret_key in INSECURE_JWT_SECRETS or len(self.jwt_secret_key) < 32):
            raise RuntimeError("JWT_SECRET_KEY must be set to a random value of at least 32 characters in production")


settings = Settings()
