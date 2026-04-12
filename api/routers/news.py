"""News and shock banner router.

GET  /api/news                 — paginated stock news feed
GET  /api/shock                — current shock banner status
POST /api/shock/{id}/dismiss   — dismiss banner for 24h
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from api.deps import get_db
from api.schemas.news import (
    NewsArticle,
    NewsFeedResponse,
    ShockEventResponse,
    ShockStatusResponse,
)
from pipeline.db.enums import NewsCategory, NewsStream, ShockBanner
from pipeline.db.models import NewsItem, ShockEvent

router = APIRouter(tags=["news"])


@router.get("/api/news", response_model=NewsFeedResponse)
def get_news(
    ticker: Optional[str] = Query(None, description="Filter by stock ticker"),
    category: Optional[str] = Query(None, description="Filter by news category"),
    stream: Optional[str] = Query(None, description="stock | general"),
    limit: int = Query(30, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> NewsFeedResponse:
    """Return paginated stock-specific news feed (Stream 1 — F-13.1)."""

    logger.info(f"GET /api/news ticker={ticker!r} category={category!r} stream={stream!r} limit={limit} offset={offset}")

    query = (
        select(NewsItem)
        .options(selectinload(NewsItem.stock))
        .order_by(NewsItem.published_at.desc())
    )

    if stream:
        query = query.where(NewsItem.stream == NewsStream(stream))

    if ticker:
        from pipeline.db.models import Stock
        stock = db.execute(
            select(Stock).where(Stock.ticker == ticker.upper())
        ).scalar_one_or_none()
        if stock:
            query = query.where(NewsItem.stock_id == stock.id)

    if category:
        query = query.where(NewsItem.category == NewsCategory(category.lower()))

    all_rows = db.execute(query).scalars().all()
    rows = all_rows[offset : offset + limit]
    logger.info(f"news → total={len(all_rows)} returning={len(rows)}")

    return NewsFeedResponse(
        articles=[
            NewsArticle(
                id=n.id,
                ticker=n.stock.ticker if n.stock else None,
                headline=n.headline,
                source=n.source,
                url=n.url,
                published_at=n.published_at,
                sentiment=n.sentiment_label,
                compound_score=n.sentiment_score,
                category=n.category,
            )
            for n in rows
        ],
        total=len(all_rows),
    )


@router.get("/api/shock", response_model=ShockStatusResponse)
def get_shock_status(db: Session = Depends(get_db)) -> ShockStatusResponse:
    """Return the current shock banner status (F-13.2.3)."""
    logger.info("GET /api/shock")

    now = datetime.now(tz=timezone.utc)

    # Most recent RED event
    latest_red = db.execute(
        select(ShockEvent)
        .where(ShockEvent.banner == ShockBanner.RED)
        .order_by(ShockEvent.triggered_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    active = (
        latest_red is not None
        and (
            latest_red.dismissed_until is None
            or latest_red.dismissed_until.replace(tzinfo=timezone.utc) < now
        )
    )

    # Recent events (last 30 days for log)
    cutoff = now - timedelta(days=30)
    recent = db.execute(
        select(ShockEvent)
        .where(ShockEvent.triggered_at >= cutoff)
        .order_by(ShockEvent.triggered_at.desc())
        .limit(20)
    ).scalars().all()

    def _to_schema(e: ShockEvent) -> ShockEventResponse:
        return ShockEventResponse(
            id=e.id,
            triggered_at=e.triggered_at,
            banner=ShockBanner(e.banner),
            headline=e.headline,
            source=e.source,
            matched_keywords=e.matched_keywords or [],
            india_vix_change_pct=e.india_vix_change_pct,
            us_vix_change_pct=e.us_vix_change_pct,
            dismissed_until=e.dismissed_until,
        )

    logger.info(f"shock → active={active} latest_red_id={latest_red.id if latest_red else None} recent_events={len(recent)}")
    return ShockStatusResponse(
        active=active,
        current_event=_to_schema(latest_red) if latest_red else None,
        recent_events=[_to_schema(e) for e in recent],
    )


@router.post("/api/shock/{event_id}/dismiss", status_code=200)
def dismiss_shock(event_id: int, db: Session = Depends(get_db)) -> dict:
    """Dismiss the shock banner for 24 hours (F-13.2.3)."""
    logger.info(f"POST /api/shock/{event_id}/dismiss")

    event = db.get(ShockEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Shock event not found")

    event.dismissed_until = datetime.now(tz=timezone.utc) + timedelta(hours=24)
    db.commit()
    return {"id": event_id, "dismissed_until": event.dismissed_until.isoformat()}
