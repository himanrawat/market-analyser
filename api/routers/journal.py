"""Trade journal router.

GET  /api/journal           — list all entries (newest first)
POST /api/journal           — create entry manually
PUT  /api/journal/{id}      — update fill price / notes / lesson
GET  /api/journal/review    — monthly review stats (win rate, lessons, etc.)
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import get_db
from api.schemas.journal import (
    CreateJournalRequest,
    JournalEntry,
    MonthlyReview,
    UpdateJournalRequest,
)
from pipeline.db.enums import ActionType
from pipeline.db.models import Stock, TradeJournalEntry

router = APIRouter(prefix="/api/journal", tags=["journal"])


@router.get("", response_model=list[JournalEntry])
def list_journal(
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[JournalEntry]:
    rows = db.execute(
        select(TradeJournalEntry)
        .order_by(TradeJournalEntry.action_date.desc())
        .limit(limit)
        .offset(offset)
    ).scalars().all()
    return [_to_schema(r, db) for r in rows]


@router.post("", status_code=201, response_model=JournalEntry)
def create_entry(body: CreateJournalRequest, db: Session = Depends(get_db)) -> JournalEntry:
    _validate_exit_learning(body.action, body.lesson)
    stock = db.execute(
        select(Stock).where(Stock.ticker == body.ticker.upper())
    ).scalar_one_or_none()

    entry = TradeJournalEntry(
        stock_id=stock.id if stock else None,
        action_type=body.action,
        bucket=body.bucket,
        action_date=body.trade_date,
        suggested_price=body.suggested_price,
        fill_price=body.actual_fill_price,
        quantity=body.qty,
        auto_thesis=body.thesis,
        user_notes=body.notes,
        exit_learning=body.lesson,
        executed=True,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return _to_schema(entry, db)


@router.put("/{entry_id}", response_model=JournalEntry)
def update_entry(
    entry_id: int,
    body: UpdateJournalRequest,
    db: Session = Depends(get_db),
) -> JournalEntry:
    entry = db.get(TradeJournalEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Journal entry not found")

    if body.actual_fill_price is not None:
        entry.fill_price = body.actual_fill_price
    if body.qty is not None:
        entry.quantity = body.qty
    if body.notes is not None:
        entry.user_notes = body.notes
    if body.lesson is not None:
        entry.exit_learning = body.lesson
    _validate_exit_learning(entry.action_type, entry.exit_learning)

    db.commit()
    db.refresh(entry)
    return _to_schema(entry, db)


@router.get("/review", response_model=list[MonthlyReview])
def monthly_review(
    months: int = Query(6, ge=1, le=24, description="How many months to include"),
    db: Session = Depends(get_db),
) -> list[MonthlyReview]:
    """Aggregate win rate, trade counts, lessons by month (F-9.4)."""
    rows = db.execute(
        select(TradeJournalEntry)
        .where(TradeJournalEntry.action_type != ActionType.SKIP_MONTH)
        .order_by(TradeJournalEntry.action_date.desc())
    ).scalars().all()

    by_month: dict[str, list[TradeJournalEntry]] = defaultdict(list)
    for r in rows:
        key = r.action_date.strftime("%Y-%m")
        by_month[key].append(r)

    reviews: list[MonthlyReview] = []
    for month in sorted(by_month.keys(), reverse=True)[:months]:
        month_rows = by_month[month]
        buys = sum(1 for r in month_rows if r.action_type == ActionType.BUY)
        sells = sum(1 for r in month_rows if r.action_type in (ActionType.SELL, ActionType.TRIM))
        lessons = sum(1 for r in month_rows if r.exit_learning)

        reviews.append(MonthlyReview(
            month=month,
            total_trades=len(month_rows),
            buys=buys,
            sells=sells,
            win_rate=None,          # requires exit price comparison — deferred
            avg_holding_days=None,
            biggest_winner=None,
            biggest_winner_pct=None,
            biggest_loser=None,
            biggest_loser_pct=None,
            lessons_logged=lessons,
        ))

    return reviews


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _to_schema(entry: TradeJournalEntry, db: Session) -> JournalEntry:
    ticker = ""
    country = None
    if entry.stock_id:
        stock = db.get(Stock, entry.stock_id)
        if stock:
            ticker = stock.ticker
            from pipeline.db.enums import Country
            country = Country(stock.country)

    return JournalEntry(
        id=entry.id,
        trade_date=entry.action_date,
        ticker=ticker,
        country=country,
        bucket=entry.bucket,
        action=entry.action_type,
        suggested_price=entry.suggested_price,
        actual_fill_price=entry.fill_price,
        qty=entry.quantity,
        broker=None,
        thesis=entry.auto_thesis,
        notes=entry.user_notes,
        lesson=entry.exit_learning,
        skipped_month=entry.action_type == ActionType.SKIP_MONTH,
    )


def _validate_exit_learning(action: ActionType, lesson: str | None) -> None:
    if action in (ActionType.SELL, ActionType.TRIM) and not (lesson or "").strip():
        raise HTTPException(status_code=400, detail="SELL and TRIM journal entries require a lesson")
