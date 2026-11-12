"""SQLAlchemy models.

Schema notes:
- All timestamps are INTEGER epoch milliseconds (UTC) — see app/clock.py.
- ``monitors.next_check_at`` drives the worker's due-monitor query.
- ``uq_incident_open`` is a partial unique index: a monitor can have at most
  one unresolved incident. The incident de-duplication rule is enforced by the
  database, not by application code.
"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .clock import now_ms
from .db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    # Unused in v1 (no auth yet); kept so enabling auth needs no migration.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False, default=now_ms)

    monitors: Mapped[list["Monitor"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )


class Monitor(Base):
    __tablename__ = "monitors"
    __table_args__ = (
        Index("idx_monitors_due", "next_check_at", sqlite_where=text("is_active = 1")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    # Optional substring the response body must contain (e.g. `"status":"ok"`).
    expected_body_contains: Mapped[str | None] = mapped_column(String(500), nullable=True)
    check_interval_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=60, server_default=text("60")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    # unknown | up | down | paused
    current_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unknown", server_default=text("'unknown'")
    )
    last_checked_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_check_at: Mapped[int] = mapped_column(Integer, nullable=False)
    last_response_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False, default=now_ms)

    user: Mapped["User"] = relationship(back_populates="monitors")
    checks: Mapped[list["Check"]] = relationship(
        back_populates="monitor", cascade="all, delete-orphan", passive_deletes=True
    )
    incidents: Mapped[list["Incident"]] = relationship(
        back_populates="monitor", cascade="all, delete-orphan", passive_deletes=True
    )


class Check(Base):
    __tablename__ = "checks"
    __table_args__ = (Index("idx_checks_monitor", "monitor_id", "checked_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    monitor_id: Mapped[int] = mapped_column(
        ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False
    )
    checked_at: Mapped[int] = mapped_column(Integer, nullable=False)
    is_success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    monitor: Mapped["Monitor"] = relationship(back_populates="checks")


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        Index(
            "uq_incident_open",
            "monitor_id",
            unique=True,
            sqlite_where=text("resolved_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    monitor_id: Mapped[int] = mapped_column(
        ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[int] = mapped_column(Integer, nullable=False)
    resolved_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    monitor: Mapped["Monitor"] = relationship(back_populates="incidents")
