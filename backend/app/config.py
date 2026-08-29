from functools import lru_cache
from typing import Self

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    backend_port: int = 8000
    frontend_origin: str = "http://localhost:3000"
    upload_dir: str = "data/uploads"

    # Demo mode: runs fully offline against local SQLite with a fixed demo
    # owner, auto-seeding the sample dataset. Automatically ON whenever no real
    # Supabase backend is configured (see demo_mode property). Set DEMO_MODE=0
    # to disable even without a Supabase backend.
    demo_mode: bool = True
    demo_owner_id: str = "demo-owner"
    seed_demo: bool = True
    demo_samples_dir: str = "data/demo-samples"
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    supabase_db_url: str = ""
    supabase_jwt_secret: str = ""

    # Google OAuth (configured in the Supabase dashboard; backend only needs
    # these if verifying id_token audience or calling Google APIs directly).
    google_client_id: str = ""
    google_client_secret: str = ""

    # Structuring LLM (OpenAI-compatible endpoint)
    llm_provider: str = "mistral"
    llm_api_key: str = ""
    llm_model: str = "mistral-small-latest"
    llm_base_url: str = "https://api.mistral.ai/v1"

    ca_email_default: str = ""
    email_dry_run: bool = True

    # Treat an empty env value (e.g. `DEMO_MODE=` left blank in .env.example)
    # as "not set", i.e. fall back to the field default. Without this, pydantic
    # raises a bool-parsing error on an empty string and a fresh clone that
    # copied .env.example verbatim would fail to boot.
    @field_validator("demo_mode", "seed_demo", "email_dry_run", mode="before")
    @classmethod
    def _empty_bool_means_default(cls, v):
        if v == "" or v is None:
            return True  # all three fields default to True
        return v

    @property
    def is_postgres(self) -> bool:
        return self.supabase_db_url.startswith("postgres")

    @property
    def has_supabase_backend(self) -> bool:
        """True when a real Supabase Postgres backend + auth are configured."""
        return bool(self.supabase_db_url and self.supabase_url)

    @property
    def demo_mode_on(self) -> bool:
        """Demo mode is ON when explicitly set, or when no real Supabase backend
        is configured (auto-detect) and demo mode isn't explicitly disabled."""
        return self.demo_mode and not self.has_supabase_backend


@lru_cache
def get_settings() -> Settings:
    return Settings()
