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
