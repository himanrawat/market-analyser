"""SQLAlchemy engine, session, and declarative base."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from pipeline.config import settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    engine = create_engine(
        settings.database_url,
        echo=False,
        future=True,
        connect_args={"check_same_thread": False}
        if settings.database_url.startswith("sqlite")
        else {},
    )

    if settings.database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA temp_store=MEMORY")
            cursor.close()

    return engine


@lru_cache(maxsize=1)
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


@contextmanager
def get_session() -> Iterator[Session]:
    """Transactional session scope. Commits on success, rolls back on error."""
    session = _session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Create all tables. Idempotent — safe to call repeatedly."""
    from pipeline.db import models  # noqa: F401 — register models on Base

    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    _apply_sqlite_schema_updates(engine)


def _apply_sqlite_schema_updates(engine: Engine) -> None:
    """Lightweight column additions for the local SQLite file.

    The project currently uses `create_all()` without Alembic migrations in the
    default local flow, so new nullable columns need a small compatibility shim
    to keep existing developer databases usable.
    """
    if engine.dialect.name != "sqlite":
        return

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "stocks" not in tables:
        return

    existing_columns = {column["name"] for column in inspector.get_columns("stocks")}
    stock_additions = {
        "isin": "VARCHAR(32)",
        "nse_symbol": "VARCHAR(32)",
        "bse_symbol": "VARCHAR(32)",
        "bse_scripcode": "VARCHAR(32)",
        "in_fno_ban": "BOOLEAN DEFAULT 0",
        "in_asm_gsm": "BOOLEAN DEFAULT 0",
    }

    with engine.begin() as connection:
        for column_name, ddl in stock_additions.items():
            if column_name not in existing_columns:
                connection.execute(text(f"ALTER TABLE stocks ADD COLUMN {column_name} {ddl}"))

    # Fundamental table: India-specific columns added in later passes
    if "fundamentals" in tables:
        existing_fund_cols = {col["name"] for col in inspector.get_columns("fundamentals")}
        fund_additions = {
            "promoter_pledge_pct": "FLOAT",
            "fii_holding": "FLOAT",
            "dii_holding": "FLOAT",
            "is_consolidated": "BOOLEAN",
            "data_source": "VARCHAR(32)",
            "gnpa_pct": "FLOAT",
            "nnpa_pct": "FLOAT",
            "nim_pct": "FLOAT",
            "casa_ratio": "FLOAT",
            "credit_cost": "FLOAT",
            "capital_adequacy_ratio": "FLOAT",
        }
        with engine.begin() as connection:
            for column_name, ddl in fund_additions.items():
                if column_name not in existing_fund_cols:
                    connection.execute(
                        text(f"ALTER TABLE fundamentals ADD COLUMN {column_name} {ddl}")
                    )
