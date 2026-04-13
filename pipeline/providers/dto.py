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
    """Single trading day OHLCV bar.

    India-specific fields (vwap, delivery_pct, delivery_volume) are optional
    and only populated when official NSE/BSE source data is available.
    """

    ticker: str
    country: Country
    date: date
    open: float
    high: float
    low: float
    close: float
    adj_close: float
    volume: int
    # India-specific: only present when sourced from official NSE/BSE data
    vwap: float | None = None                # Volume-Weighted Average Price
    delivery_pct: float | None = None        # % of traded volume that was delivery-based
    delivery_volume: int | None = None       # Delivery quantity (absolute)


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

    # India-specific ownership
    promoter_pledge_pct: float | None = None   # % of promoter shares pledged
    fii_holding: float | None = None           # Foreign Institutional Investor %
    dii_holding: float | None = None           # Domestic Institutional Investor %

    # India-specific statement metadata
    is_consolidated: bool | None = None        # consolidated=True, standalone=False
    data_source: str | None = None             # 'nse', 'bse', 'yfinance', etc.

    # India sector-specific (banks / NBFCs)
    gnpa_pct: float | None = None              # Gross NPA %
    nnpa_pct: float | None = None              # Net NPA %
    nim_pct: float | None = None               # Net Interest Margin %
    casa_ratio: float | None = None            # CASA ratio %
    credit_cost: float | None = None           # Credit cost %
    capital_adequacy_ratio: float | None = None  # CAR / CRAR %


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


class QuarterlyEstimate(_Base):
    """Forward analyst estimate for a fiscal period."""

    period: str
    fiscal_date: date | None = None
    eps_estimate: float | None = None
    revenue_estimate: float | None = None
    analyst_count: int | None = None


class AnalystForecastSnapshot(_Base):
    """Aggregated analyst target / rating / EPS estimate summary."""

    ticker: str
    country: Country
    analyst_count: int | None = None
    buy_count: int | None = None
    hold_count: int | None = None
    sell_count: int | None = None
    target_high: float | None = None
    target_low: float | None = None
    target_avg: float | None = None
    current_price: float | None = None
    consensus_rating: str | None = None
    quarterly_estimates: list[QuarterlyEstimate] = Field(default_factory=list)


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
    isin: str | None = None
    nse_symbol: str | None = None
    bse_symbol: str | None = None
    bse_scripcode: str | None = None
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
    isin: str | None = None
    nse_symbol: str | None = None
    bse_symbol: str | None = None
    bse_scripcode: str | None = None


# ---------------------------------------------------------------------------
# India-specific data records
# ---------------------------------------------------------------------------


class BulkDealRecord(_Base):
    """A single bulk or block deal disclosure from NSE or BSE."""

    ticker: str
    country: Country
    deal_type: str                    # 'bulk' or 'block'
    trade_date: date
    client_name: str | None = None    # buyer or seller name
    transaction_type: str | None = None  # 'BUY' or 'SELL'
    quantity: float | None = None
    trade_price: float | None = None
    source: str = "NSE"               # 'NSE' or 'BSE'
    raw: dict[str, Any] = Field(default_factory=dict)


class InsiderTradeRecord(_Base):
    """A single insider / promoter trade disclosure (SEBI PIT/SAST regulations)."""

    ticker: str
    country: Country
    person_name: str | None = None
    person_category: str | None = None   # 'Promoter', 'Director', 'KMP', etc.
    transaction_type: str | None = None  # 'Acquisition', 'Disposal', etc.
    trade_date: date | None = None
    from_date: date | None = None
    to_date: date | None = None
    shares_traded: float | None = None
    trade_price: float | None = None
    post_trade_pct: float | None = None  # % holding after trade
    source: str = "NSE"
    raw: dict[str, Any] = Field(default_factory=dict)


class MarketDepthLevel(_Base):
    """One price level in a bid or ask depth ladder."""

    price: float
    quantity: int
    orders: int | None = None


class MarketDepthSnapshot(_Base):
    """Top-5 bid/ask depth snapshot for a stock at a point in time."""

    ticker: str
    country: Country
    snapshot_at: datetime
    buy_depth: list[MarketDepthLevel] = Field(default_factory=list)
    sell_depth: list[MarketDepthLevel] = Field(default_factory=list)
    total_buy_qty: int | None = None
    total_sell_qty: int | None = None
    source: str = "NSE"


class DerivativesSentiment(_Base):
    """Aggregated F&O sentiment data for a stock or index.

    Used for support/resistance mapping, expiry-week analysis, and PCR signals.
    """

    ticker: str
    country: Country
    as_of: date
    # Open Interest
    oi_futures: float | None = None
    oi_futures_change: float | None = None
    oi_call_total: float | None = None
    oi_put_total: float | None = None
    # PCR
    put_call_ratio: float | None = None
    # Max pain
    max_pain_strike: float | None = None
    # Option chain summary
    atm_iv: float | None = None          # At-the-money implied volatility %
    top_call_oi_strike: float | None = None
    top_put_oi_strike: float | None = None
    source: str = "NSE"
    raw_summary: dict[str, Any] = Field(default_factory=dict)


class MarketBreadthSnapshot(_Base):
    """Market-wide advance/decline breadth and index context for a given date."""

    as_of: date
    # Advance / decline
    advances: int | None = None
    declines: int | None = None
    unchanged: int | None = None
    advance_decline_ratio: float | None = None
    # India VIX
    india_vix: float | None = None
    india_vix_change_pct: float | None = None
    # Index levels
    nifty_50: float | None = None
    nifty_50_change_pct: float | None = None
    sensex: float | None = None
    sensex_change_pct: float | None = None
    # Sector indices
    nifty_bank: float | None = None
    nifty_it: float | None = None
    nifty_fmcg: float | None = None
    nifty_auto: float | None = None
    nifty_pharma: float | None = None
    nifty_realty: float | None = None
    nifty_metal: float | None = None
    nifty_energy: float | None = None
    source: str = "NSE"
