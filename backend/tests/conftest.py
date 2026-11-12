from __future__ import annotations

import httpx
import pytest
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401  (register mappers)
from app.clock import now_ms
from app.db import Base, create_db_engine


@pytest.fixture()
def session():
    """Isolated in-memory SQLite database with the demo user seeded.

    Built with the production engine factory so the SQLite pragmas (notably
    foreign_keys=ON) and the partial indexes are exercised by tests.
    """
    engine = create_db_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with factory() as db:
        db.add(models.User(id=1, email="demo@local", password_hash="!", created_at=now_ms()))
        db.commit()
        yield db

    engine.dispose()


@pytest.fixture()
async def client(session):
    """HTTP client bound to the app, sharing the test session."""
    from app.db import get_db
    from app.main import app

    def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http

    app.dependency_overrides.clear()
