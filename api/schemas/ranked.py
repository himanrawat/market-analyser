"""Response schemas for /api/ranked."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from pipeline.db.enums import Bucket, Country, MacroRegime


class RankedStock(BaseModel):
    ticker: str
    country: Country
    bucket: Bucket
    rank: int
    score: float
    qualified: bool
    is_actionable: bool        # True if rank <= picks_per_bucket
    factor_scores: dict[str, float]
    reason: str

    # Fundamental display data (from DB, may be None if not yet fetched)
    company_name: Optional[str]
    sector: Optional[str]
    market_cap: Optional[float]
    pe_ratio: Optional[float]
    pb_ratio: Optional[float]
    roe: Optional[float]
    dividend_yield: Optional[float]

    # Technical
    above_200dma: Optional[bool]
    momentum_12m_1m: Optional[float]

    # Guardrail flags
    earnings_soon: bool = False         # earnings within 14 days
    recent_earnings_beat: bool = False


class BucketList(BaseModel):
    bucket: Bucket
    country: Country
    macro_regime: MacroRegime
    shock_regime: bool
    picks_per_bucket: int
    ranked: list[RankedStock]      # actionable (top N)
    extended: list[RankedStock]    # browse-only (beyond top N)
    removed_by_blackout: list[str]
    removed_by_sector_cap: list[str]
    notes: list[str]


class RankedResponse(BaseModel):
    lists: list[BucketList]
    run_date: Optional[str]         # date of last rebalance snapshot
