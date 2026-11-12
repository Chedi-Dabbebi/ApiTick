"""The lightweight column migration in ``init_db`` (no Alembic in this project)."""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.pool import StaticPool

from app.db import create_db_engine, init_db

# The monitors table as it looked before body assertions were added.
OLD_MONITORS_DDL = """
CREATE TABLE monitors (
    id INTEGER NOT NULL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    name VARCHAR(120) NOT NULL,
    url TEXT NOT NULL,
    check_interval_seconds INTEGER NOT NULL DEFAULT 60,
    is_active BOOLEAN NOT NULL DEFAULT 1,
    current_status VARCHAR(16) NOT NULL DEFAULT 'unknown',
    last_checked_at INTEGER,
    next_check_at INTEGER NOT NULL,
    last_response_time_ms INTEGER,
    last_status_code INTEGER,
    created_at INTEGER NOT NULL
)
"""


def test_init_db_adds_body_assertion_column_to_an_existing_database():
    engine = create_db_engine("sqlite://", poolclass=StaticPool)
    with engine.begin() as connection:
        connection.execute(text(OLD_MONITORS_DDL))

    init_db(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("monitors")}
    assert "expected_body_contains" in columns


def test_init_db_migration_is_idempotent():
    engine = create_db_engine("sqlite://", poolclass=StaticPool)

    init_db(engine)
    init_db(engine)  # must not try to add the column a second time

    columns = {column["name"] for column in inspect(engine).get_columns("monitors")}
    assert "expected_body_contains" in columns
