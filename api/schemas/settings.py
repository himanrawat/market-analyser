"""Response schemas for /api/settings."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from pipeline.db.enums import Bucket


class BucketWeight(BaseModel):
    bucket: Bucket
    allocation_pct: float     # 0–100


class SettingsResponse(BaseModel):
    picks_per_bucket: int                     # 5 / 10 / 15 / 20
    bucket_allocations: list[BucketWeight]    # must sum to 100
    rebalance_day: int                        # default 7
    telegram_enabled: bool
    email_enabled: bool
    stock_news_enabled: bool
    shock_detection_enabled: bool
    universe_nifty: str                       # "nifty50" | "nifty500"
    universe_sp: str                          # "sp100" | "sp500"


class UpdateSettingsRequest(BaseModel):
    picks_per_bucket: Optional[int] = None
    bucket_allocations: Optional[list[BucketWeight]] = None
    rebalance_day: Optional[int] = None
    telegram_enabled: Optional[bool] = None
    email_enabled: Optional[bool] = None
    stock_news_enabled: Optional[bool] = None
    shock_detection_enabled: Optional[bool] = None
    universe_nifty: Optional[str] = None
    universe_sp: Optional[str] = None
