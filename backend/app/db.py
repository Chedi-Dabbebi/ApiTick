"""Engine, session factory, and schema bootstrap.

SQLite is used by both the API process and the worker process, so every
connection gets WAL mode (readers don't block the writer) and a busy timeout
(instead of an immediate "database is locked" error).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "monitor.db"

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH.as_posix()}")

DEMO_USER_ID = 1


class Base(DeclarativeBase):
    pass


def create_db_engine(url: str = DATABASE_URL, **kwargs) -> Engine:
    """Create an engine with the SQLite pragmas this app depends on."""
    if url.startswith("sqlite"):
        kwargs.setdefault("connect_args", {"check_same_thread": False, "timeout": 5.0})

    engine = create_engine(url, **kwargs)

    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _set_pragmas(dbapi_connection, _connection_record):  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


engine = create_db_engine()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one short-lived session per request."""
    with SessionLocal() as session:
        yield session


def _ensure_monitor_columns(target: Engine) -> None:
    """Add columns introduced after the first release (no migration tool).

    ``create_all`` only creates missing tables, so an existing database would
    otherwise fail with "no such column" as soon as a model gains a field.
    """
    columns = {column["name"] for column in inspect(target).get_columns("monitors")}
    if "expected_body_contains" not in columns:
        with target.begin() as connection:
            connection.execute(
                text("ALTER TABLE monitors ADD COLUMN expected_body_contains VARCHAR(500)")
            )


def init_db(target: Engine | None = None) -> None:
    """Create tables, apply small column additions, and seed the demo user."""
    from . import models  # noqa: F401  (register mappers before create_all)
    from .clock import now_ms

    if target is None:
        DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        target = engine

    Base.metadata.create_all(target)
    _ensure_monitor_columns(target)

    factory = SessionLocal if target is engine else sessionmaker(bind=target, expire_on_commit=False)

    with factory() as session:
        if session.get(models.User, DEMO_USER_ID) is None:
            session.add(
                models.User(
                    id=DEMO_USER_ID,
                    email="demo@local",
                    password_hash="!",  # placeholder until auth exists
                    created_at=now_ms(),
                )
            )
            session.commit()
