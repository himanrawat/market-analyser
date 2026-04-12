"""GET /api/ranked — 8 ranked lists (4 buckets × 2 countries) with filters."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from api.deps import get_db
from api.schemas.ranked import BucketList, RankedResponse, RankedStock
from pipeline.db.enums import Bucket, Country, MacroRegime
from pipeline.db.models import RebalanceSnapshot, Score, Stock
from pipeline.portfolio.diff import _format_reason
from pipeline.scoring.base import ScoreOutput

router = APIRouter(prefix="/api/ranked", tags=["ranked"])

_ALL_BUCKETS = list(Bucket)
_ALL_COUNTRIES = list(Country)


@router.get("", response_model=RankedResponse)
def get_ranked(
    bucket: Optional[str] = Query(None, description="Filter by bucket slug"),
    country: Optional[str] = Query(None, description="Filter by country (IN/US)"),
    sector: Optional[str] = Query(None, description="Filter by sector name"),
    pe_sort: Optional[str] = Query(None, description="pe_asc | pe_desc"),
    pb_sort: Optional[str] = Query(None, description="pb_asc | pb_desc"),
    picks: int = Query(10, ge=5, le=20, description="Top-N actionable per list"),
    db: Session = Depends(get_db),
) -> RankedResponse:
    """Return ranked lists from the most recent rebalance snapshot."""

    logger.info(f"GET /api/ranked bucket={bucket!r} country={country!r} sector={sector!r} picks={picks}")

    # Latest snapshot
    snapshot = db.execute(
        select(RebalanceSnapshot).order_by(RebalanceSnapshot.run_date.desc()).limit(1)
    ).scalar_one_or_none()

    if snapshot is None:
        logger.warning("ranked: no rebalance snapshot found — returning empty lists")
        return RankedResponse(lists=[], run_date=None)

    # Filter buckets/countries
    buckets = [Bucket(bucket)] if bucket else _ALL_BUCKETS
    countries = [Country(country)] if country else _ALL_COUNTRIES

    lists: list[BucketList] = []

    for b in buckets:
        for c in countries:
            score_rows = db.execute(
                select(Score)
                .options(selectinload(Score.stock))
                .where(
                    Score.snapshot_id == snapshot.id,
                    Score.bucket == b,
                )
            ).scalars().all()

            # Filter by country via joined stock
            score_rows = [s for s in score_rows if s.stock.country == c]

            # Optional sector filter
            if sector:
                score_rows = [
                    s for s in score_rows
                    if s.stock.sector and sector.lower() in s.stock.sector.lower()
                ]

            # Build RankedStock objects
            ranked_stocks = [_build_ranked_stock(s, b, c, picks) for s in score_rows]

            # Sort: default by rank/score, then optional valuation sort
            ranked_stocks = _apply_sort(ranked_stocks, pe_sort, pb_sort)

            actionable = [r for r in ranked_stocks if r.is_actionable]
            extended = [r for r in ranked_stocks if not r.is_actionable]

            lists.append(BucketList(
                bucket=b,
                country=c,
                macro_regime=MacroRegime(snapshot.macro_regime),
                shock_regime=snapshot.shock_regime,
                picks_per_bucket=picks,
                ranked=actionable,
                extended=extended,
                removed_by_blackout=[],
                removed_by_sector_cap=[],
                notes=[],
            ))

    total_actionable = sum(len(lst.ranked) for lst in lists)
    total_extended = sum(len(lst.extended) for lst in lists)
    logger.info(f"ranked → snapshot={snapshot.run_date} lists={len(lists)} actionable={total_actionable} extended={total_extended}")
    return RankedResponse(
        lists=lists,
        run_date=str(snapshot.run_date),
    )


def _build_ranked_stock(
    score_row: Score,
    bucket: Bucket,
    country: Country,
    picks: int,
) -> RankedStock:
    stock = score_row.stock
    fund = _latest_fundamental(stock)

    # Reconstruct ScoreOutput for reason formatting
    so = ScoreOutput(
        ticker=stock.ticker,
        bucket=bucket,
        score=score_row.score,
        qualified=score_row.qualified,
        factor_scores=score_row.factor_scores or {},
        rank=score_row.rank,
    )
    reason = _format_reason(so)

    return RankedStock(
        ticker=stock.ticker,
        country=country,
        bucket=bucket,
        rank=score_row.rank or 999,
        score=score_row.score,
        qualified=score_row.qualified,
        is_actionable=score_row.rank is not None and score_row.rank <= picks,
        factor_scores=score_row.factor_scores or {},
        reason=reason,
        company_name=stock.name,
        sector=stock.sector,
        market_cap=stock.market_cap,
        pe_ratio=fund.pe if fund else None,
        pb_ratio=fund.pb if fund else None,
        roe=fund.roe if fund else None,
        dividend_yield=fund.dividend_yield if fund else None,
        above_200dma=None,          # not stored on score row directly
        momentum_12m_1m=score_row.factor_scores.get("momentum_12m_1m") if score_row.factor_scores else None,
        earnings_soon=False,        # would need events join — left for v2
        recent_earnings_beat=False,
    )


def _latest_fundamental(stock: Stock):
    """Return the most recently stored fundamental row for a stock."""
    if not stock.fundamentals:
        return None
    return max(stock.fundamentals, key=lambda f: f.fiscal_date)


def _apply_sort(
    stocks: list[RankedStock],
    pe_sort: Optional[str],
    pb_sort: Optional[str],
) -> list[RankedStock]:
    if pe_sort == "pe_asc":
        return sorted(stocks, key=lambda s: (s.pe_ratio is None, s.pe_ratio or 0))
    if pe_sort == "pe_desc":
        return sorted(stocks, key=lambda s: (s.pe_ratio is None, -(s.pe_ratio or 0)))
    if pb_sort == "pb_asc":
        return sorted(stocks, key=lambda s: (s.pb_ratio is None, s.pb_ratio or 0))
    if pb_sort == "pb_desc":
        return sorted(stocks, key=lambda s: (s.pb_ratio is None, -(s.pb_ratio or 0)))
    # Default: rank ascending, unranked at the bottom
    return sorted(stocks, key=lambda s: (s.rank is None, s.rank or 999))
