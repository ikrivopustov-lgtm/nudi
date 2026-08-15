"""Test env: isolated temp SQLite per session, set before nudge modules cache paths."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Defaults before any nudge import that reads settings.
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123:test")
os.environ.setdefault("TELEGRAM_ALLOWED_USER_ID", "42")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")


@pytest.fixture(scope="session", autouse=True)
def _isolated_db(tmp_path_factory):
    """Point DATABASE_PATH at a fresh file and reset the SQLAlchemy engine."""
    db_dir = tmp_path_factory.mktemp("nudge_db")
    db_file = db_dir / "test.db"
    os.environ["DATABASE_PATH"] = str(db_file)

    from nudge.config import get_settings
    from nudge.db import init_db, reset_engine

    get_settings.cache_clear()
    reset_engine()
    init_db()
    yield db_file
    reset_engine()
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _clean_tables(_isolated_db):
    """Wipe task/action/conversation rows between tests for isolation."""
    from sqlalchemy import text

    from nudge.db import get_engine, init_db

    init_db()
    engine = get_engine()
    with engine.begin() as conn:
        for table in ("actionlog", "convturn", "task", "setting"):
            conn.execute(text(f"DELETE FROM {table}"))
    yield
