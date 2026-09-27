"""Shared fixtures. The default suite never touches the network or an LLM."""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from newsalpha.core.config import get_settings


@pytest.fixture(scope="session")
def live_db() -> Iterator[None]:
    """Skip the test unless the configured Postgres is reachable."""
    engine = create_engine(get_settings().database_url, connect_args={"connect_timeout": 3})
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError as exc:
        pytest.skip(f"Postgres not reachable: {exc.orig}")
    finally:
        engine.dispose()
    yield
