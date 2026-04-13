"""GET /api/dashboard — India dashboard header and market context."""
from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import get_db
from api.routers._event_utils import format_event_description
from api.schemas.dashboard import (
    DashboardResponse,
    IndiaBreadthSnapshot,
    IndexQuote,
    MacroSnapshot,
    ShockBannerStatus,
    UpcomingEvent,
    VixReading,
)
from pipeline.db.enums import Country, MacroRegime, ShockBanner
from pipeline.db.models import (
    Event,
    IndiaMarketBreadth,
    MacroSnapshot as MacroSnapshotModel,
    ShockEvent,
    Stock,
)
from pipeline.providers.registry import get_data_provider
from pipeline.scoring.guardrails import compute_macro_regime

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardResponse)
def get_dashboard(db: Session = Depends(get_db)) -> DashboardResponse:
    """Return everything needed to render the India-first dashboard header."""
    logger.info("GET /api/dashboard")

    # Latest macro snapshot
    macro_row = db.execute(
        select(MacroSnapshotModel).order_by(MacroSnapshotModel.date.desc()).limit(1)
    ).scalar_one_or_none()

    if macro_row:
        logger.debug(f"dashboard: macro_row date={macro_row.date}, nifty={macro_row.nifty_50_close}, sp500={macro_row.sp_500_close}")
    else:
        logger.warning("dashboard: no macro snapshot found in DB — all fields will be null")

    breadth_row = db.execute(
        select(IndiaMarketBreadth).order_by(IndiaMarketBreadth.as_of.desc()).limit(1)
    ).scalar_one_or_none()
    live_breadth = breadth_row
    if breadth_row is None:
        live_breadth = _load_live_breadth(get_data_provider())

    repo_rate = _resolve_repo_rate(db, macro_row)
    india_cpi_yoy = _resolve_india_cpi_yoy(db, macro_row)

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

    # Upcoming India events (next 14 days)
    cutoff = date_type.today()
    end = cutoff + timedelta(days=14)
    event_rows = db.execute(
        select(Event)
        .join(Stock, Stock.id == Event.stock_id)
        .where(
            Stock.country == Country.INDIA,
            Event.event_date >= cutoff,
            Event.event_date <= end,
        )
        .order_by(Event.event_date)
        .limit(20)
    ).scalars().all()

    def _idx(name: str, close: float | None, change_1d_pct: float | None = None) -> IndexQuote:
        return IndexQuote(
            name=name,
            value=close,
            change_1d=None,
            change_1d_pct=change_1d_pct,
            change_1m_pct=None,
            change_1y_pct=None,
        )

    indices: list[IndexQuote] = []
    sector_indices: list[IndexQuote] = []
    if live_breadth:
        indices = [
            _idx("Nifty 50", live_breadth.nifty_50, live_breadth.nifty_50_change_pct),
            _idx("Sensex", live_breadth.sensex, live_breadth.sensex_change_pct),
        ]
        sector_indices = [
            _idx("Nifty Bank", live_breadth.nifty_bank),
            _idx("Nifty IT", live_breadth.nifty_it),
            _idx("Nifty FMCG", live_breadth.nifty_fmcg),
            _idx("Nifty Auto", live_breadth.nifty_auto),
            _idx("Nifty Pharma", live_breadth.nifty_pharma),
            _idx("Nifty Realty", live_breadth.nifty_realty),
            _idx("Nifty Metal", live_breadth.nifty_metal),
            _idx("Nifty Energy", live_breadth.nifty_energy),
        ]
        sector_indices = [idx for idx in sector_indices if idx.value is not None]
    elif macro_row:
        indices = [
            _idx("Nifty 50", macro_row.nifty_50_close),
        ]
    indices = [idx for idx in indices if idx.value is not None]

    macro_ts = (
        datetime.combine(macro_row.date, datetime.min.time(), tzinfo=timezone.utc)
        if macro_row
        else None
    )
    breadth_ts = (
        datetime.combine(live_breadth.as_of, datetime.min.time(), tzinfo=timezone.utc)
        if live_breadth
        else None
    )

    logger.info(
        "dashboard → regime={} shock_active={} indices={} sectors={} events={}".format(
            regime,
            shock_active,
            len(indices),
            len(sector_indices),
            len(event_rows),
        )
    )
    return DashboardResponse(
        indices=indices,
        sector_indices=sector_indices,
        vix=VixReading(
            india_vix=(
                live_breadth.india_vix
                if live_breadth and live_breadth.india_vix is not None
                else (macro_row.india_vix if macro_row else None)
            ),
            us_vix=macro_row.us_vix if macro_row else None,
            as_of=breadth_ts or macro_ts,
        ),
        macro=MacroSnapshot(
            regime=regime,
            shock_regime=shock_active,
            fed_funds_rate=macro_row.fed_funds_rate if macro_row else None,
            rbi_repo_rate=repo_rate,
            us_cpi_yoy=macro_row.us_cpi_yoy if macro_row else None,
            india_cpi_yoy=india_cpi_yoy,
            usd_inr=macro_row.usd_inr if macro_row else None,
            us_10y_yield=macro_row.us_10y_yield if macro_row else None,
            oil_price=macro_row.brent_oil if macro_row else None,
            as_of=macro_ts,
        ),
        breadth=(
            IndiaBreadthSnapshot(
                as_of=live_breadth.as_of,
                advances=live_breadth.advances,
                declines=live_breadth.declines,
                unchanged=live_breadth.unchanged,
                advance_decline_ratio=live_breadth.advance_decline_ratio,
                india_vix=live_breadth.india_vix,
                india_vix_change_pct=live_breadth.india_vix_change_pct,
            )
            if live_breadth
            else None
        ),
        upcoming_events=[
            UpcomingEvent(
                ticker=e.stock.ticker if e.stock else None,
                event_type=e.event_type,
                event_date=e.event_date,
                description=format_event_description(e.meta),
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


def _load_live_breadth(data_provider):
    try:
        breadth = data_provider.india.get_market_breadth()
        if breadth is None:
            return None
        if breadth.advances is None and breadth.nifty_50 is None:
            return None
        return breadth
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"dashboard: live breadth unavailable: {exc}")
        return None


def _latest_non_null_macro_value(db: Session, column_name: str) -> float | None:
    column = getattr(MacroSnapshotModel, column_name)
    return db.execute(
        select(column)
        .where(column.is_not(None))
        .order_by(MacroSnapshotModel.date.desc())
        .limit(1)
    ).scalar_one_or_none()


def _load_live_macro_series(indicator: str):
    provider = get_data_provider()
    try:
        end = date_type.today()
        start = end - timedelta(days=550)
        return provider.macro.get_series(indicator, start, end)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"dashboard: live macro {indicator} unavailable: {exc}")
        return []


def _resolve_repo_rate(
    db: Session,
    macro_row: MacroSnapshotModel | None,
) -> float | None:
    if macro_row and macro_row.rbi_repo_rate is not None:
        return macro_row.rbi_repo_rate
    latest = _latest_non_null_macro_value(db, "rbi_repo_rate")
    if latest is not None:
        return latest
    series = _load_live_macro_series("INDIA_REPO_RATE")
    return series[-1].value if series else None


def _resolve_india_cpi_yoy(
    db: Session,
    macro_row: MacroSnapshotModel | None,
) -> float | None:
    if macro_row and macro_row.india_cpi_yoy is not None:
        return macro_row.india_cpi_yoy
    latest = _latest_non_null_macro_value(db, "india_cpi_yoy")
    if latest is not None:
        return latest
    series = _load_live_macro_series("INDIA_CPI_YOY")
    return series[-1].value if series else None
