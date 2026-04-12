"""Response schemas for /api/portfolio."""
from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel

from pipeline.db.enums import Country


class HoldingRow(BaseModel):
    id: int
    ticker: str
    name: str
    sector: Optional[str]
    country: Country
    qty: float
    avg_buy_price: float
    buy_date: Optional[date]
    current_price: Optional[float]
    current_value: Optional[float]
    cost_basis: float
    unrealized_pnl: Optional[float]
    unrealized_pnl_pct: Optional[float]
    days_held: Optional[int]
    ltcg_warning: bool     # India: holding approaching 12 months → warn at 11m
    pct_of_portfolio: Optional[float]


class SectorAllocation(BaseModel):
    sector: str
    value: float
    pct: float
    over_concentrated: bool   # True if > 25%


class BenchmarkReturn(BaseModel):
    name: str
    return_pct: Optional[float]


class PortfolioSummary(BaseModel):
    total_value: float
    total_cost: float
    total_pnl: float
    total_pnl_pct: float
    india_value: float
    us_value: float
    india_pct: float
    us_pct: float
    sector_allocation: list[SectorAllocation]
    benchmarks: list[BenchmarkReturn]


class PortfolioResponse(BaseModel):
    holdings: list[HoldingRow]
    summary: PortfolioSummary


class AddHoldingRequest(BaseModel):
    ticker: str
    country: Country
    qty: float
    avg_buy_price: float
    buy_date: Optional[date] = None


class UpdateHoldingRequest(BaseModel):
    qty: Optional[float] = None
    avg_buy_price: Optional[float] = None
    buy_date: Optional[date] = None
