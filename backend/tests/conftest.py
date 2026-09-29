"""Shared fixtures. The default suite never touches the network or an LLM.

Database tests run against a separate ``<name>_test`` database on the same server, never the
development database: the migration round-trip test drops every table.
"""

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from newsalpha.core.config import Settings


def _test_database_url() -> str:
    """TEST_DATABASE_URL if set, else DATABASE_URL with ``_test`` appended to the db name."""
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit
    url = make_url(Settings().database_url)
    return url.set(database=f"{url.database}_test").render_as_string(hide_password=False)


TEST_DATABASE_URL = _test_database_url()
if not (make_url(TEST_DATABASE_URL).database or "").endswith("_test"):
    raise RuntimeError(f"refusing to run tests against a non-test database: {TEST_DATABASE_URL}")

# Must happen before anything calls get_settings(), which caches (conftest is imported first).
os.environ["DATABASE_URL"] = TEST_DATABASE_URL


def _ensure_database_exists() -> None:
    url = make_url(TEST_DATABASE_URL)
    admin = create_engine(
        url.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": 3},
    )
    try:
        with admin.connect() as conn:
            exists = conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": url.database}
            )
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    finally:
        admin.dispose()


@pytest.fixture(scope="session")
def live_db() -> Iterator[None]:
    """Create the test database if needed; skip the test when Postgres is unreachable."""
    try:
        _ensure_database_exists()
    except OperationalError as exc:
        pytest.skip(f"Postgres not reachable: {exc.orig}")
    yield
