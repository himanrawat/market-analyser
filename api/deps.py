"""FastAPI dependencies shared across routers."""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy.orm import Session

from pipeline.db.base import get_engine
from sqlalchemy.orm import sessionmaker

_SessionLocal = sessionmaker(bind=get_engine(), autocommit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    """Yield a SQLAlchemy session; close it when the request finishes."""
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()
