"""GET /api/dashboard — macro snapshot, index strip, VIX, regime, upcoming events, shock banner."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import get_db
from api.schemas.dashboard import (
    DashboardResponse,
    IndexQuote,
    MacroSnapshot,
    ShockBannerStatus,
    UpcomingEvent,
    VixReading,
)
from pipeline.db.enums import MacroRegime, ShockBanner
from pipeline.db.models import Event, MacroSnapshot as MacroSnapshotModel, ShockEvent
from pipeline.scoring.guardrails import compute_macro_regime

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardResponse)
def get_dashboard(db: Session = Depends(get_db)) -> DashboardResponse:
    """Return everything needed to render the main dashboard header."""
    logger.info("GET /api/dashboard")

    # Latest macro snapshot
    macro_row = db.execute(
        select(MacroSnapshotModel).order_by(MacroSnapshotModel.date.desc()).limit(1)
    ).scalar_one_or_none()

    if macro_row:
        logger.debug(f"dashboard: macro_row date={macro_row.date}, nifty={macro_row.nifty_50_close}, sp500={macro_row.sp_500_close}")
    else:
        logger.warning("dashboard: no macro snapshot found in DB — all fields will be null")

    # Regime
    if macro_row:
        regime = compute_macro_regime(
            macro_row.nifty_50_close,
            macro_row.nifty_50_200dma,
            macro_row.sp_500_close,
            macro_row.sp_500_200dma,
        )
    else:
        regime = MacroRegime.RISK_ON

    # Active shock event
    shock_event = db.execute(
        select(ShockEvent)
        .where(ShockEvent.banner == ShockBanner.RED)
        .order_by(ShockEvent.triggered_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    now = datetime.now(tz=timezone.utc)
    shock_active = (
        shock_event is not None
        and (
            shock_event.dismissed_until is None
            or shock_event.dismissed_until.replace(tzinfo=timezone.utc) < now
        )
    )

    # Upcoming events (next 14 days)
    from datetime import timedelta
    from datetime import date as date_type
    cutoff = date_type.today()
    end = cutoff + timedelta(days=14)
    event_rows = db.execute(
        select(Event)
        .where(Event.event_date >= cutoff, Event.event_date <= end)
        .order_by(Event.event_date)
        .limit(20)
    ).scalars().all()

    # Build index quotes from macro row
    def _idx(name: str, close: float | None, dma: float | None) -> IndexQuote:
        return IndexQuote(
            name=name,
            value=close,
            change_1d=None,
            change_1d_pct=None,
            change_1m_pct=None,
            change_1y_pct=None,
        )

    indices = []
    if macro_row:
        indices = [
            _idx("Nifty 50", macro_row.nifty_50_close, macro_row.nifty_50_200dma),
            _idx("S&P 500", macro_row.sp_500_close, macro_row.sp_500_200dma),
        ]

    macro_ts = (
        datetime.combine(macro_row.date, datetime.min.time(), tzinfo=timezone.utc)
        if macro_row
        else None
    )

    logger.info(f"dashboard → regime={regime} shock_active={shock_active} indices={len(indices)} events={len(event_rows)}")
    return DashboardResponse(
        indices=indices,
        vix=VixReading(
            india_vix=macro_row.india_vix if macro_row else None,
            us_vix=macro_row.us_vix if macro_row else None,
            as_of=macro_ts,
        ),
        macro=MacroSnapshot(
            regime=regime,
            shock_regime=shock_active,
            fed_funds_rate=macro_row.fed_funds_rate if macro_row else None,
            rbi_repo_rate=macro_row.rbi_repo_rate if macro_row else None,
            us_cpi_yoy=macro_row.us_cpi_yoy if macro_row else None,
            india_cpi_yoy=macro_row.india_cpi_yoy if macro_row else None,
            usd_inr=macro_row.usd_inr if macro_row else None,
            us_10y_yield=macro_row.us_10y_yield if macro_row else None,
            oil_price=macro_row.brent_oil if macro_row else None,
            as_of=macro_ts,
        ),
        upcoming_events=[
            UpcomingEvent(
                ticker=e.stock.ticker if e.stock else None,
                event_type=e.event_type,
                event_date=e.event_date,
                description=str(e.meta) if e.meta else None,
            )
            for e in event_rows
        ],
        shock=ShockBannerStatus(
            active=shock_active,
            banner=ShockBanner(shock_event.banner) if shock_event else None,
            headline=shock_event.headline if shock_event else None,
            triggered_at=shock_event.triggered_at if shock_event else None,
            dismissed_until=shock_event.dismissed_until if shock_event else None,
        ),
        as_of=now,
    )
