"""Response schemas for /api/stocks/{ticker}."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field

from pipeline.db.enums import Bucket, Country, SentimentLabel


class FundamentalData(BaseModel):
    revenue: Optional[float]
    net_income: Optional[float]
    eps: Optional[float]
    roe: Optional[float]
    roce: Optional[float]
    debt_equity: Optional[float]
    free_cash_flow: Optional[float]
    pe_ratio: Optional[float]
    pb_ratio: Optional[float]
    peg_ratio: Optional[float]
    dividend_yield: Optional[float]
    payout_ratio: Optional[float]
    promoter_holding: Optional[float] = None
    promoter_pledge_pct: Optional[float] = None
    fii_holding: Optional[float] = None
    dii_holding: Optional[float] = None
    is_consolidated: Optional[bool] = None
    data_source: Optional[str] = None
    gnpa_pct: Optional[float] = None
    nnpa_pct: Optional[float] = None
    nim_pct: Optional[float] = None
    casa_ratio: Optional[float] = None
    credit_cost: Optional[float] = None
    capital_adequacy_ratio: Optional[float] = None
    as_of: Optional[date]


class PricePoint(BaseModel):
    date: date
    close: float
    volume: Optional[float]


class ScoreBucket(BaseModel):
    bucket: Bucket
    score: float
    qualified: bool
    rank: Optional[int]
    factor_scores: dict[str, float]
    reason: str


class NewsItem(BaseModel):
    id: int
    headline: str
    source: str
    url: Optional[str]
    published_at: Optional[datetime]
    sentiment: Optional[SentimentLabel]
    compound_score: Optional[float]
    category: Optional[str]


class AnalystForecast(BaseModel):
    analyst_count: Optional[int]
    buy_count: Optional[int]
    hold_count: Optional[int]
    sell_count: Optional[int]
    target_high: Optional[float]
    target_low: Optional[float]
    target_avg: Optional[float]
    current_price: Optional[float]
    consensus_rating: Optional[str] = None
    availability: Optional[str] = None
    note: Optional[str] = None
    quarterly_estimates: list["QuarterlyEstimate"] = Field(default_factory=list)


class QuarterlyEstimate(BaseModel):
    period: str
    fiscal_date: Optional[date]
    eps_estimate: Optional[float]
    revenue_estimate: Optional[float]
    analyst_count: Optional[int]


class PeerStock(BaseModel):
    ticker: str
    company_name: Optional[str]
    pe_ratio: Optional[float]
    roe: Optional[float]
    growth_rate: Optional[float]
    market_cap: Optional[float]
    bucket_membership: list[Bucket]


class HoldingDetail(BaseModel):
    qty: float
    avg_buy_price: float
    buy_date: Optional[date]
    current_price: Optional[float]
    current_value: Optional[float]
    unrealized_pnl: Optional[float]
    unrealized_pnl_pct: Optional[float]
    days_held: Optional[int]
    ltcg_warning: bool        # True if 11 months held (India)
    pct_of_portfolio: Optional[float]


class EventItem(BaseModel):
    event_type: str
    event_date: Optional[date]
    description: Optional[str]


class SentimentSummary(BaseModel):
    positive_count: int
    neutral_count: int
    negative_count: int
    avg_compound: Optional[float]
    headline_volume_30d: int


class QuoteSnapshot(BaseModel):
    date: Optional[date]
    open: Optional[float]
    high: Optional[float]
    low: Optional[float]
    close: Optional[float]
    volume: Optional[float]
    vwap: Optional[float] = None
    delivery_pct: Optional[float] = None
    delivery_volume: Optional[float] = None
    source: Optional[str] = None


class IndiaGuardrailFlags(BaseModel):
    in_fno_ban: bool
    in_asm_gsm: bool
    promoter_pledge_pct: Optional[float] = None


class DepthLevel(BaseModel):
    price: float
    quantity: int
    orders: Optional[int] = None


class MarketDepthSnapshot(BaseModel):
    snapshot_at: datetime
    buy_depth: list[DepthLevel] = Field(default_factory=list)
    sell_depth: list[DepthLevel] = Field(default_factory=list)
    total_buy_qty: Optional[int] = None
    total_sell_qty: Optional[int] = None
    source: Optional[str] = None


class DerivativesSnapshot(BaseModel):
    as_of: date
    oi_futures: Optional[float] = None
    oi_futures_change: Optional[float] = None
    oi_call_total: Optional[float] = None
    oi_put_total: Optional[float] = None
    put_call_ratio: Optional[float] = None
    max_pain_strike: Optional[float] = None
    atm_iv: Optional[float] = None
    top_call_oi_strike: Optional[float] = None
    top_put_oi_strike: Optional[float] = None
    source: Optional[str] = None


class BulkDealItem(BaseModel):
    deal_type: str
    trade_date: date
    client_name: Optional[str]
    transaction_type: Optional[str]
    quantity: Optional[float]
    trade_price: Optional[float]
    source: Optional[str]


class InsiderTradeItem(BaseModel):
    person_name: Optional[str]
    person_category: Optional[str]
    transaction_type: Optional[str]
    trade_date: Optional[date]
    from_date: Optional[date]
    to_date: Optional[date]
    shares_traded: Optional[float]
    trade_price: Optional[float]
    post_trade_pct: Optional[float]
    source: Optional[str]


class StockDetailResponse(BaseModel):
    ticker: str
    country: Country
    company_name: Optional[str]
    sector: Optional[str]
    description: Optional[str] = None
    market_cap: Optional[float]
    current_price: Optional[float]
    isin: Optional[str] = None
    nse_symbol: Optional[str] = None
    bse_symbol: Optional[str] = None
    bse_scripcode: Optional[str] = None
    latest_quote: Optional[QuoteSnapshot] = None
    india_guardrails: Optional[IndiaGuardrailFlags] = None
    market_depth: Optional[MarketDepthSnapshot] = None
    derivatives: Optional[DerivativesSnapshot] = None
    recent_bulk_deals: list[BulkDealItem] = Field(default_factory=list)
    recent_insider_trades: list[InsiderTradeItem] = Field(default_factory=list)

    # Tabs
    fundamentals: Optional[FundamentalData]
    sentiment: Optional[SentimentSummary]
    forecasts: Optional[AnalystForecast]
    peers: list[PeerStock]
    peers_note: Optional[str] = None
    holding: Optional[HoldingDetail]
    events: list[EventItem]
    news: list[NewsItem]

    # Score breakdown (F-7.8)
    scores: list[ScoreBucket]
    plain_english_reason: str          # F-7.9

    # Chart data (last 12 months)
    price_history: list[PricePoint]
