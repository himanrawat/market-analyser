"""Response schemas for /api/actions."""
from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field

from pipeline.db.enums import ActionType, Bucket, Country


class ActionRow(BaseModel):
    ticker: str
    country: Country
    bucket: Bucket
    action: ActionType
    score: float
    rank: Optional[int]

    current_qty: Optional[float]
    current_value: Optional[float]
    current_price: Optional[float]

    suggested_amount: Optional[float]
    suggested_qty: Optional[float]

    reason: str
    factor_scores: dict[str, float]
    executed: bool


class BucketAllocation(BaseModel):
    bucket: Bucket
    pct: float           # 0.0–1.0
    amount: float        # derived from fresh_capital


class DeploymentPlan(BaseModel):
    fresh_capital: float
    sell_proceeds: float
    total_available: float
    bucket_allocations: list[BucketAllocation]
    action_amounts: dict[str, float]   # "<ticker>|<bucket>" → amount
    undeployed: float


class ActionsResponse(BaseModel):
    run_date: date
    macro_regime: str
    shock_regime: bool
    buys: list[ActionRow]
    sells: list[ActionRow]
    adds: list[ActionRow]
    holds: list[ActionRow]
    plan: Optional[DeploymentPlan]


class ExecuteRequest(BaseModel):
    action: ActionType
    bucket: Bucket
    country: Country
    actual_fill_price: float = Field(gt=0)
    qty: float = Field(gt=0)
    notes: Optional[str] = None
    lesson: Optional[str] = None


class SkipMonthRequest(BaseModel):
    reason: str


class RefreshPricesResponse(BaseModel):
    updated: dict[str, float]   # ticker → latest price
    as_of: str
