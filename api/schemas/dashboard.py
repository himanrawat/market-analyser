"""Response schemas for /api/dashboard."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel

from pipeline.db.enums import MacroRegime, ShockBanner


class IndexQuote(BaseModel):
    name: str
    value: Optional[float]
    change_1d: Optional[float]
    change_1d_pct: Optional[float]
    change_1m_pct: Optional[float]
    change_1y_pct: Optional[float]


class VixReading(BaseModel):
    india_vix: Optional[float]
    us_vix: Optional[float]
    as_of: Optional[datetime]


class MacroSnapshot(BaseModel):
    regime: MacroRegime
    shock_regime: bool
    fed_funds_rate: Optional[float]
    rbi_repo_rate: Optional[float]
    us_cpi_yoy: Optional[float]
    india_cpi_yoy: Optional[float]
    usd_inr: Optional[float]
    us_10y_yield: Optional[float]
    oil_price: Optional[float]
    as_of: Optional[datetime]


class UpcomingEvent(BaseModel):
    ticker: Optional[str]
    event_type: str
    event_date: date
    description: Optional[str]


class ShockBannerStatus(BaseModel):
    active: bool
    banner: Optional[ShockBanner]
    headline: Optional[str]
    triggered_at: Optional[datetime]
    dismissed_until: Optional[datetime]


class DashboardResponse(BaseModel):
    indices: list[IndexQuote]
    vix: VixReading
    macro: MacroSnapshot
    upcoming_events: list[UpcomingEvent]
    shock: ShockBannerStatus
    as_of: datetime
