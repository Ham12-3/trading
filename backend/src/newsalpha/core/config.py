"""Application settings loaded from environment variables and `.env`."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(RuntimeError):
    """A required setting is missing or invalid."""


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
    openai_api_key: str | None = Field(default=None, repr=False)
    cors_origins: list[str] = ["http://localhost:3000"]

    # Paths are relative to backend/ unless absolute.
    data_dir: Path = Path("data")
    universe_path: Path = Path("config/universe.yaml")

    # SEC EDGAR: identify ourselves and stay under the 10 req/s fair-access limit.
    sec_user_agent_name: str | None = None
    sec_user_agent_email: str | None = None
    sec_max_requests_per_second: float = Field(default=5.0, gt=0, le=10)

    def sec_user_agent(self) -> str:
        """The User-Agent EDGAR requires ("Name email"); raises if not configured."""
        if not self.sec_user_agent_name or not self.sec_user_agent_email:
            raise ConfigError(
                "SEC_USER_AGENT_NAME and SEC_USER_AGENT_EMAIL must be set in .env; "
                "EDGAR rejects requests without a descriptive User-Agent."
            )
        return f"{self.sec_user_agent_name} {self.sec_user_agent_email}"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
