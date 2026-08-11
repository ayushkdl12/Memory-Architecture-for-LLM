from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Base

engine = create_engine(settings.database_url, pool_pre_ping=True)
Base.metadata.create_all(bind=engine, checkfirst=True)


@pytest.fixture
def db() -> Generator[Session, None, None]:
    """Transactional test session — every test rolls back its changes."""
    conn = engine.connect()
    trans = conn.begin()
    session = Session(bind=conn)
    try:
        yield session
    finally:
        session.close()
        conn.close()
