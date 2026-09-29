"""Alembic migrations apply cleanly against a real database."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


@pytest.mark.db
def test_upgrade_and_downgrade_roundtrip(live_db: None) -> None:
    cfg = Config(str(ALEMBIC_INI))
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
