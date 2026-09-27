"""Application settings loaded from environment variables and `.env`."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Secrets come only from the environment, never from code."""

    model_config = SettingsConfigDict(
        # Commands run from backend/, so ../.env is the repo-root file; a local .env wins.
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://newsalpha:newsalpha@localhost:5432/newsalpha"
    anthropic_api_key: str | None = Field(default=None, repr=False)
    sec_user_agent_name: str | None = None
    sec_user_agent_email: str | None = None
    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
