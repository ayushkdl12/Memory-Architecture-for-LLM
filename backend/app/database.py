from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .config import settings
from . import models  # noqa: F401  (register models with Base.metadata)

engine = create_engine(settings.database_url, pool_pre_ping=True)

# Make sure the schema/objects exist. checkfirst=True skips anything already
# created by db/schema.sql, so this also works on a fresh database.
models.Base.metadata.create_all(bind=engine, checkfirst=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()