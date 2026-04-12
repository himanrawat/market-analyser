"""Response schemas for /api/news and /api/shock."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from pipeline.db.enums import NewsCategory, SentimentLabel, ShockBanner


class NewsArticle(BaseModel):
    id: int
    ticker: Optional[str]
    headline: str
    source: str
    url: Optional[str]
    published_at: Optional[datetime]
    sentiment: Optional[SentimentLabel]
    compound_score: Optional[float]
    category: Optional[NewsCategory]


class NewsFeedResponse(BaseModel):
    articles: list[NewsArticle]
    total: int


class ShockEventResponse(BaseModel):
    id: int
    triggered_at: datetime
    banner: ShockBanner
    headline: str
    source: str
    matched_keywords: list[str]
    india_vix_change_pct: Optional[float]
    us_vix_change_pct: Optional[float]
    dismissed_until: Optional[datetime]


class ShockStatusResponse(BaseModel):
    active: bool
    current_event: Optional[ShockEventResponse]
    recent_events: list[ShockEventResponse]   # last 30 days
