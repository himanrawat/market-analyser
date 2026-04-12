"""Pydantic DTOs used at the provider boundary.

These are intentionally NOT the SQLAlchemy models — they're the shape of data
flowing *in* from vendors. The pipeline's ingest step maps DTOs → ORM rows.
Separating them means a vendor quirk (e.g. different field name) is absorbed
in one place rather than leaking into the schema or scoring layers.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from pipeline.db.enums import Country, EventType, IndexName


class _Base(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PriceBar(_Base):
    """Single trading day OHLCV bar."""

    ticker: str
    country: Country
    date: date
    open: float
    high: float
    low: float
    close: float
    adj_close: float
    volume: int


class FundamentalSnapshot(_Base):
    """Quarterly fundamental snapshot. All fields optional because vendors
    vary wildly in completeness — scoring handles missing values."""

    ticker: str
    country: Country
    fiscal_date: date
    period: str  # e.g. "Q1-FY26" or "2026Q1"

    revenue: float | None = None
    net_income: float | None = None
    eps: float | None = None

    total_debt: float | None = None
    total_equity: float | None = None
    debt_equity: float | None = None

    operating_cash_flow: float | None = None
    free_cash_flow: float | None = None

    roe: float | None = None
    roce: float | None = None
    gross_margin: float | None = None
    operating_margin: float | None = None
    net_margin: float | None = None

    pe: float | None = None
    peg: float | None = None
    pb: float | None = None
    ev_ebitda: float | None = None

    dividend_per_share: float | None = None
    dividend_yield: float | None = None
    payout_ratio: float | None = None

    promoter_holding: float | None = None


class NewsArticle(_Base):
    """One news headline. `ticker` is None for general (market-wide) news."""

    source: str
    headline: str
    url: str
    published_at: datetime
    summary: str | None = None
    ticker: str | None = None
    country: Country | None = None


class EventRecord(_Base):
    """Corporate event — earnings, ex-dividend, split, etc."""

    ticker: str
    country: Country
    event_type: EventType
    event_date: date
    meta: dict[str, Any] = Field(default_factory=dict)


class MacroReading(_Base):
    """One (date, value) data point for a named macro series."""

    indicator: str  # e.g. "FEDFUNDS", "USDINR", "INDIA_VIX"
    date: date
    value: float


class UniverseConstituent(_Base):
    """A single member of an index (Nifty 500, S&P 500, …)."""

    index_name: IndexName
    ticker: str
    country: Country
    name: str
    sector: str | None = None
    industry: str | None = None
    as_of: date


class StockProfile(_Base):
    """Mostly-static stock metadata used when first adding a stock to `stocks`."""

    ticker: str
    country: Country
    name: str
    sector: str | None = None
    industry: str | None = None
    currency: str
    market_cap: float | None = None
    listing_date: date | None = None
    description: str | None = None
