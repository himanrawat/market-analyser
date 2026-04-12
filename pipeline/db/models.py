"""ORM models for the entire market-analyser database.

Schema notes:
- All monetary columns store the native currency of the stock (INR for IN, USD for US).
  Market cap is normalized to the stock's local currency as well.
- All dates are UTC dates (naive — we never cross timezone boundaries in stored data).
- JSON-heavy columns use SQLAlchemy's JSON type which maps to TEXT on SQLite.
- Indexes are opinionated around the read patterns the pipeline + API will use:
  * stock lookups by ticker+country
  * prices by (stock_id, date) for range scans
  * news by (stock_id, published_at) for feed pagination
  * snapshots by (run_date, country, bucket) for ranked-list queries
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pipeline.db.base import Base
from pipeline.db.enums import (
    ActionType,
    Broker,
    Bucket,
    Country,
    EventType,
    IndexName,
    MacroRegime,
    NewsCategory,
    NewsStream,
    SentimentLabel,
    ShockBanner,
)


# ---------------------------------------------------------------------------
# Universe
# ---------------------------------------------------------------------------


class Stock(Base):
    """The canonical stock row. One row per (ticker, country)."""

    __tablename__ = "stocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False)
    country: Mapped[Country] = mapped_column(String(4), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    sector: Mapped[str | None] = mapped_column(String(128))
    industry: Mapped[str | None] = mapped_column(String(128))
    currency: Mapped[str] = mapped_column(String(8), nullable=False)  # INR / USD
    market_cap: Mapped[float | None] = mapped_column(Float)  # local currency, absolute
    listing_date: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_suspended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    in_fno_ban: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # India
    description: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    prices: Mapped[list[Price]] = relationship(back_populates="stock", cascade="all, delete-orphan")
    fundamentals: Mapped[list[Fundamental]] = relationship(
        back_populates="stock", cascade="all, delete-orphan"
    )
    news_items: Mapped[list[NewsItem]] = relationship(
        back_populates="stock", cascade="all, delete-orphan"
    )
    events: Mapped[list[Event]] = relationship(
        back_populates="stock", cascade="all, delete-orphan"
    )
    scores: Mapped[list[Score]] = relationship(
        back_populates="stock", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("ticker", "country", name="uq_stock_ticker_country"),
        Index("ix_stock_country_active", "country", "is_active"),
        Index("ix_stock_sector", "sector"),
    )


class UniverseMembership(Base):
    """Tracks which index a stock belonged to over time. Supports quarterly
    constituent refresh without losing history. Survivorship bias aware."""

    __tablename__ = "universe_memberships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    index_name: Mapped[IndexName] = mapped_column(String(16), nullable=False)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False)
    country: Mapped[Country] = mapped_column(String(4), nullable=False)
    added_date: Mapped[date] = mapped_column(Date, nullable=False)
    removed_date: Mapped[date | None] = mapped_column(Date)

    __table_args__ = (
        Index("ix_universe_index_ticker", "index_name", "ticker"),
        Index("ix_universe_active", "index_name", "removed_date"),
    )


# ---------------------------------------------------------------------------
# Prices & fundamentals
# ---------------------------------------------------------------------------


class Price(Base):
    """Daily OHLCV. 3 years on first fetch, daily incremental thereafter."""

    __tablename__ = "prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    adj_close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(Integer, nullable=False)

    stock: Mapped[Stock] = relationship(back_populates="prices")

    __table_args__ = (
        UniqueConstraint("stock_id", "date", name="uq_price_stock_date"),
        Index("ix_price_stock_date", "stock_id", "date"),
    )


class Fundamental(Base):
    """Quarterly fundamentals. One row per stock per fiscal quarter end."""

    __tablename__ = "fundamentals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False
    )
    fiscal_date: Mapped[date] = mapped_column(Date, nullable=False)
    period: Mapped[str] = mapped_column(String(8), nullable=False)  # e.g. "Q1-FY26"

    # Income statement
    revenue: Mapped[float | None] = mapped_column(Float)
    net_income: Mapped[float | None] = mapped_column(Float)
    eps: Mapped[float | None] = mapped_column(Float)

    # Balance sheet
    total_debt: Mapped[float | None] = mapped_column(Float)
    total_equity: Mapped[float | None] = mapped_column(Float)
    debt_equity: Mapped[float | None] = mapped_column(Float)

    # Cash flow
    operating_cash_flow: Mapped[float | None] = mapped_column(Float)
    free_cash_flow: Mapped[float | None] = mapped_column(Float)

    # Ratios
    roe: Mapped[float | None] = mapped_column(Float)
    roce: Mapped[float | None] = mapped_column(Float)
    gross_margin: Mapped[float | None] = mapped_column(Float)
    operating_margin: Mapped[float | None] = mapped_column(Float)
    net_margin: Mapped[float | None] = mapped_column(Float)

    # Valuation (point-in-time snapshot at quarter end)
    pe: Mapped[float | None] = mapped_column(Float)
    peg: Mapped[float | None] = mapped_column(Float)
    pb: Mapped[float | None] = mapped_column(Float)
    ev_ebitda: Mapped[float | None] = mapped_column(Float)

    # Dividend
    dividend_per_share: Mapped[float | None] = mapped_column(Float)
    dividend_yield: Mapped[float | None] = mapped_column(Float)
    payout_ratio: Mapped[float | None] = mapped_column(Float)

    # India-specific
    promoter_holding: Mapped[float | None] = mapped_column(Float)

    stock: Mapped[Stock] = relationship(back_populates="fundamentals")

    __table_args__ = (
        UniqueConstraint("stock_id", "fiscal_date", name="uq_fundamental_stock_date"),
        Index("ix_fundamental_stock_date", "stock_id", "fiscal_date"),
    )


# ---------------------------------------------------------------------------
# News, events, macro
# ---------------------------------------------------------------------------


class NewsItem(Base):
    """Both stock-specific (stream='stock') and general market news
    (stream='general'). General items have stock_id=NULL."""

    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stream: Mapped[NewsStream] = mapped_column(String(16), nullable=False)
    stock_id: Mapped[int | None] = mapped_column(
        ForeignKey("stocks.id", ondelete="CASCADE")
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    category: Mapped[NewsCategory] = mapped_column(
        String(16), nullable=False, default=NewsCategory.OTHER
    )
    sentiment_score: Mapped[float | None] = mapped_column(Float)  # VADER compound [-1, 1]
    sentiment_label: Mapped[SentimentLabel | None] = mapped_column(String(16))

    # Shock detector support
    matched_keywords: Mapped[list[str] | None] = mapped_column(JSON)

    stock: Mapped[Stock | None] = relationship(back_populates="news_items")

    __table_args__ = (
        UniqueConstraint("url", name="uq_news_url"),
        Index("ix_news_stock_published", "stock_id", "published_at"),
        Index("ix_news_stream_published", "stream", "published_at"),
    )


class Event(Base):
    """Upcoming or past corporate events: earnings dates, ex-div, splits, etc."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[EventType] = mapped_column(String(32), nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    stock: Mapped[Stock] = relationship(back_populates="events")

    __table_args__ = (
        Index("ix_event_stock_date", "stock_id", "event_date"),
        Index("ix_event_date_type", "event_date", "event_type"),
    )


class MacroSnapshot(Base):
    """Daily macro indicators. Single row per date — no composite key needed."""

    __tablename__ = "macro_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, unique=True)

    # Rates
    fed_funds_rate: Mapped[float | None] = mapped_column(Float)
    rbi_repo_rate: Mapped[float | None] = mapped_column(Float)
    us_10y_yield: Mapped[float | None] = mapped_column(Float)
    india_10y_yield: Mapped[float | None] = mapped_column(Float)

    # Inflation
    us_cpi_yoy: Mapped[float | None] = mapped_column(Float)
    india_cpi_yoy: Mapped[float | None] = mapped_column(Float)

    # FX & volatility
    usd_inr: Mapped[float | None] = mapped_column(Float)
    india_vix: Mapped[float | None] = mapped_column(Float)
    us_vix: Mapped[float | None] = mapped_column(Float)

    # Commodities
    brent_oil: Mapped[float | None] = mapped_column(Float)
    gold: Mapped[float | None] = mapped_column(Float)

    # Index levels (for 200 DMA regime check)
    nifty_50_close: Mapped[float | None] = mapped_column(Float)
    nifty_50_200dma: Mapped[float | None] = mapped_column(Float)
    sp_500_close: Mapped[float | None] = mapped_column(Float)
    sp_500_200dma: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (Index("ix_macro_date", "date"),)


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------


class Holding(Base):
    """Current positions. Manually entered in v1 (no CSV import)."""

    __tablename__ = "holdings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("stocks.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    avg_buy_price: Mapped[float] = mapped_column(Float, nullable=False)
    buy_date: Mapped[date] = mapped_column(Date, nullable=False)
    broker: Mapped[Broker] = mapped_column(String(16), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    stock: Mapped[Stock] = relationship()

    __table_args__ = (Index("ix_holding_stock", "stock_id"),)


# ---------------------------------------------------------------------------
# Rebalance run (the monthly snapshot)
# ---------------------------------------------------------------------------


class RebalanceSnapshot(Base):
    """One row per monthly pipeline run. Immutable after creation — provides
    the audit trail required by G5 ('permanent record of every decision')."""

    __tablename__ = "rebalance_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_date: Mapped[date] = mapped_column(Date, nullable=False, unique=True)
    run_started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    run_completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Regime tags at run time
    macro_regime: Mapped[MacroRegime] = mapped_column(String(16), nullable=False)
    shock_regime: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Pipeline metadata
    universe_size_raw: Mapped[int | None] = mapped_column(Integer)
    universe_size_filtered: Mapped[int | None] = mapped_column(Integer)
    config_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    errors: Mapped[list[str] | None] = mapped_column(JSON)

    scores: Mapped[list[Score]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_snapshot_run_date", "run_date"),)


class Score(Base):
    """Per-stock, per-bucket, per-run score. The core output of the pipeline.

    A stock can have up to 4 Score rows per RebalanceSnapshot (one per bucket).
    `qualified=True` means it survived all disqualifiers and guardrails and
    is eligible for the ranked top-N list. `rank` is set only for qualifiers."""

    __tablename__ = "scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("rebalance_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False
    )
    bucket: Mapped[Bucket] = mapped_column(String(32), nullable=False)

    score: Mapped[float] = mapped_column(Float, nullable=False)  # 0-100
    qualified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rank: Mapped[int | None] = mapped_column(Integer)  # NULL if not in top-N

    # Per-factor breakdown for score explainability (F-7.8, F-7.9)
    factor_scores: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False)
    disqualifiers: Mapped[list[str] | None] = mapped_column(JSON)

    # Snapshot of the fields needed to render a score card without re-fetching
    snapshot_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    snapshot: Mapped[RebalanceSnapshot] = relationship(back_populates="scores")
    stock: Mapped[Stock] = relationship(back_populates="scores")

    __table_args__ = (
        UniqueConstraint("snapshot_id", "stock_id", "bucket", name="uq_score_snap_stock_bucket"),
        Index("ix_score_snap_bucket_rank", "snapshot_id", "bucket", "rank"),
        Index("ix_score_snap_bucket_score", "snapshot_id", "bucket", "score"),
    )


# ---------------------------------------------------------------------------
# Trade journal
# ---------------------------------------------------------------------------


class TradeJournalEntry(Base):
    """One entry per executed (or skipped) action. F-9.1–F-9.4."""

    __tablename__ = "trade_journal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("rebalance_snapshots.id", ondelete="SET NULL")
    )
    stock_id: Mapped[int | None] = mapped_column(
        ForeignKey("stocks.id", ondelete="SET NULL")
    )
    action_type: Mapped[ActionType] = mapped_column(String(16), nullable=False)
    bucket: Mapped[Bucket | None] = mapped_column(String(32))

    action_date: Mapped[date] = mapped_column(Date, nullable=False)
    suggested_price: Mapped[float | None] = mapped_column(Float)
    fill_price: Mapped[float | None] = mapped_column(Float)
    quantity: Mapped[float | None] = mapped_column(Float)

    auto_thesis: Mapped[str | None] = mapped_column(Text)
    user_notes: Mapped[str | None] = mapped_column(Text)
    exit_learning: Mapped[str | None] = mapped_column(Text)  # F-9.3 prompt

    executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_journal_action_date", "action_date"),
        Index("ix_journal_stock", "stock_id"),
    )


# ---------------------------------------------------------------------------
# Shock events
# ---------------------------------------------------------------------------


class ShockEvent(Base):
    """Every RED/YELLOW banner trigger. F-13.2.8 — with retrospective tagging."""

    __tablename__ = "shock_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    triggered_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    banner: Mapped[ShockBanner] = mapped_column(String(16), nullable=False)

    headline: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    url: Mapped[str | None] = mapped_column(Text)

    # Signal A
    matched_keywords: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    # Signal B
    india_vix_at_trigger: Mapped[float | None] = mapped_column(Float)
    us_vix_at_trigger: Mapped[float | None] = mapped_column(Float)
    india_vix_change_pct: Mapped[float | None] = mapped_column(Float)
    us_vix_change_pct: Mapped[float | None] = mapped_column(Float)

    # User interaction
    dismissed_until: Mapped[datetime | None] = mapped_column(DateTime)

    # Retrospective review
    outcome_30d_return: Mapped[float | None] = mapped_column(Float)
    retrospective_label: Mapped[str | None] = mapped_column(String(16))  # true/false/unknown

    __table_args__ = (
        Index("ix_shock_triggered", "triggered_at"),
        Index("ix_shock_banner", "banner", "triggered_at"),
    )


# ---------------------------------------------------------------------------
# Settings (key-value for tunables)
# ---------------------------------------------------------------------------


class SettingKV(Base):
    """Key-value store for settings F-11.*. Kept deliberately simple because
    there are few settings and they all fit into JSON values."""

    __tablename__ = "settings_kv"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
