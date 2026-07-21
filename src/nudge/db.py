"""SQLite engine, WAL mode, schema init, and session helper.

Kept independent of the full pydantic config so it can be used standalone (tests,
scripts). The database path comes from DATABASE_PATH (default: data/nudge.db).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

# Import models so their tables register on SQLModel.metadata before create_all.
from . import models  # noqa: F401

_DEFAULT_PATH = "data/nudge.db"
_engine: Engine | None = None


@event.listens_for(Engine, "connect")
def _set_sqlite_pragmas(dbapi_conn, _record) -> None:
    """Enable WAL + sane durability/foreign-key defaults on every connection."""
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def db_path() -> Path:
    return Path(os.getenv("DATABASE_PATH", _DEFAULT_PATH))


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        path = db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: PTB runs handlers/jobs on a different thread pool.
        _engine = create_engine(
            f"sqlite:///{path}",
            connect_args={"check_same_thread": False},
        )
    return _engine


def init_db() -> None:
    """Create tables if missing. Idempotent."""
    SQLModel.metadata.create_all(get_engine())


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional session: commit on success, rollback on error."""
    session = Session(get_engine())
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
