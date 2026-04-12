"""Response schemas for /api/journal."""
from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel

from pipeline.db.enums import ActionType, Broker, Bucket, Country


class JournalEntry(BaseModel):
    id: int
    trade_date: date
    ticker: str
    country: Optional[Country]
    bucket: Optional[Bucket]
    action: ActionType
    suggested_price: Optional[float]
    actual_fill_price: Optional[float]
    qty: Optional[float]
    broker: Optional[Broker]
    thesis: Optional[str]
    notes: Optional[str]
    lesson: Optional[str]       # required on SELL/TRIM (F-9.3)
    skipped_month: bool


class MonthlyReview(BaseModel):
    month: str          # "2026-04"
    total_trades: int
    buys: int
    sells: int
    win_rate: Optional[float]       # % of closed positions profitable
    avg_holding_days: Optional[float]
    biggest_winner: Optional[str]   # ticker
    biggest_winner_pct: Optional[float]
    biggest_loser: Optional[str]
    biggest_loser_pct: Optional[float]
    lessons_logged: int


class CreateJournalRequest(BaseModel):
    trade_date: date
    ticker: str
    country: Country
    bucket: Optional[Bucket] = None
    action: ActionType
    suggested_price: Optional[float] = None
    actual_fill_price: Optional[float] = None
    qty: Optional[float] = None
    broker: Optional[Broker] = None
    thesis: Optional[str] = None
    notes: Optional[str] = None
    lesson: Optional[str] = None


class UpdateJournalRequest(BaseModel):
    actual_fill_price: Optional[float] = None
    qty: Optional[float] = None
    notes: Optional[str] = None
    lesson: Optional[str] = None
    broker: Optional[Broker] = None
