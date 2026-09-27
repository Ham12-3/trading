"""Settings loading."""

import pytest

from newsalpha.core.config import Settings


def test_settings_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    settings = Settings(_env_file=None)
    assert settings.database_url.endswith("@db:5432/x")
    assert settings.anthropic_api_key == "test-key-not-real"


def test_api_key_is_not_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    assert "test-key-not-real" not in repr(Settings(_env_file=None))
