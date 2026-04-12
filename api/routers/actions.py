"""Actions router — portfolio diff, execute, skip-month, refresh-prices.

GET  /api/actions                    — current diff result
POST /api/actions/{ticker}/execute   — mark action executed, create journal entry
POST /api/actions/skip-month         — log a deliberate skip
GET  /api/actions/refresh-prices     — pull 15-min delayed quotes for action list
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from api.deps import get_db
from api.schemas.actions import (
    ActionRow,
    ActionsResponse,
    BucketAllocation,
    DeploymentPlan,
    ExecuteRequest,
    RefreshPricesResponse,
    SkipMonthRequest,
)
from pipeline.db.enums import ActionType, Broker, Bucket, Country
from pipeline.db.models import (
    Holding,
    Price,
    RebalanceSnapshot,
    Score,
    SettingKV,
    Stock,
    TradeJournalEntry,
)
from pipeline.portfolio.diff import UNDERWEIGHT_THRESHOLD, _format_reason
from pipeline.portfolio.planner import CapitalPlanner, DEFAULT_BUCKET_ALLOCATION
from pipeline.scoring.base import ScoreOutput
from pipeline.scoring.guardrails import HYSTERESIS_BUFFER

router = APIRouter(prefix="/api/actions", tags=["actions"])


@router.get("", response_model=ActionsResponse)
def get_actions(
    fresh_capital: float = Query(0.0, description="Fresh capital to deploy"),
    sell_proceeds: float = Query(0.0, description="Proceeds from sells"),
    bucket_alloc_quality_value: float | None = Query(None, ge=0.0),
    bucket_alloc_momentum: float | None = Query(None, ge=0.0),
    bucket_alloc_quality_momentum: float | None = Query(None, ge=0.0),
    bucket_alloc_dividend_growth: float | None = Query(None, ge=0.0),
    db: Session = Depends(get_db),
) -> ActionsResponse:
    """Return the portfolio diff from the most recent rebalance snapshot."""

    snapshot = db.execute(
        select(RebalanceSnapshot).order_by(RebalanceSnapshot.run_date.desc()).limit(1)
    ).scalar_one_or_none()

    if snapshot is None:
        raise HTTPException(status_code=404, detail="No rebalance snapshot found. Run the pipeline first.")

    # Re-run diff from stored snapshot data (avoids re-scoring)
    score_rows = db.execute(
        select(Score)
        .options(selectinload(Score.stock))
        .where(Score.snapshot_id == snapshot.id)
    ).scalars().all()

    holdings = db.execute(
        select(Holding).options(selectinload(Holding.stock))
    ).scalars().all()

    action_rows = _build_action_rows(score_rows, holdings, snapshot, db)

    buys = [a for a in action_rows if a.action == ActionType.BUY]
    sells = [a for a in action_rows if a.action == ActionType.SELL]
    adds = [a for a in action_rows if a.action == ActionType.ADD]
    holds = [a for a in action_rows if a.action == ActionType.HOLD]

    # Capital plan
    plan = None
    if fresh_capital > 0 or sell_proceeds > 0:
        from pipeline.portfolio.diff import ActionRow as DiffActionRow

        bucket_allocations = _load_bucket_allocation(
            db,
            bucket_alloc_quality_value=bucket_alloc_quality_value,
            bucket_alloc_momentum=bucket_alloc_momentum,
            bucket_alloc_quality_momentum=bucket_alloc_quality_momentum,
            bucket_alloc_dividend_growth=bucket_alloc_dividend_growth,
        )
        diff_rows = [
            DiffActionRow(
                ticker=a.ticker,
                country=a.country,
                bucket=a.bucket,
                action=a.action,
                score=a.score,
                rank=a.rank,
            )
            for a in buys + adds
        ]
        planner = CapitalPlanner(bucket_allocation=bucket_allocations)
        deployment = planner.plan(diff_rows, fresh_capital=fresh_capital, sell_proceeds=sell_proceeds)
        _apply_capital_plan(action_rows, deployment.action_amounts)
        plan = DeploymentPlan(
            fresh_capital=fresh_capital,
            sell_proceeds=sell_proceeds,
            total_available=deployment.total_available,
            bucket_allocations=[
                BucketAllocation(
                    bucket=b,
                    pct=bucket_allocations.get(b, 0.0),
                    amount=amt,
                )
                for b, amt in deployment.bucket_allocations.items()
            ],
            action_amounts=deployment.action_amounts,
            undeployed=deployment.undeployed,
        )

    return ActionsResponse(
        run_date=snapshot.run_date,
        macro_regime=snapshot.macro_regime,
        shock_regime=snapshot.shock_regime,
        buys=buys,
        sells=sells,
        adds=adds,
        holds=holds,
        plan=plan,
    )


@router.post("/{ticker}/execute", status_code=201)
def execute_action(
    ticker: str,
    body: ExecuteRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Mark an action as executed and create a trade journal entry."""

    stock = db.execute(
        select(Stock).where(
            Stock.ticker == ticker.upper(),
            Stock.country == body.country,
        )
    ).scalar_one_or_none()
    if stock is None:
        raise HTTPException(status_code=404, detail=f"Stock {ticker} not found")
    if body.action == ActionType.HOLD:
        raise HTTPException(status_code=400, detail="HOLD actions cannot be executed")
    if body.action in (ActionType.SELL, ActionType.TRIM) and not (body.lesson or "").strip():
        raise HTTPException(status_code=400, detail="Exit actions require a one-line lesson")

    snapshot = db.execute(
        select(RebalanceSnapshot).order_by(RebalanceSnapshot.run_date.desc()).limit(1)
    ).scalar_one_or_none()
    if snapshot is None:
        raise HTTPException(status_code=404, detail="No rebalance snapshot found")

    existing = db.execute(
        select(TradeJournalEntry).where(
            TradeJournalEntry.snapshot_id == snapshot.id,
            TradeJournalEntry.stock_id == stock.id,
            TradeJournalEntry.bucket == body.bucket,
            TradeJournalEntry.action_type == body.action,
            TradeJournalEntry.executed.is_(True),
        )
    ).scalar_one_or_none()
    if existing is not None:
        return {"id": existing.id, "ticker": ticker.upper(), "status": "already_executed"}

    score_row = db.execute(
        select(Score).where(
            Score.snapshot_id == snapshot.id,
            Score.stock_id == stock.id,
            Score.bucket == body.bucket,
        )
    ).scalar_one_or_none()

    _apply_execution_to_holding(db, stock, body)

    entry = TradeJournalEntry(
        snapshot_id=snapshot.id,
        stock_id=stock.id,
        action_type=body.action,
        bucket=body.bucket,
        action_date=date.today(),
        suggested_price=_suggested_price_for_score(score_row),
        fill_price=body.actual_fill_price,
        quantity=body.qty,
        auto_thesis=_score_reason(score_row, stock),
        user_notes=body.notes,
        exit_learning=body.lesson,
        executed=True,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return {"id": entry.id, "ticker": ticker.upper(), "status": "executed"}


@router.post("/skip-month", status_code=201)
def skip_month(body: SkipMonthRequest, db: Session = Depends(get_db)) -> dict:
    """Log a deliberate skip-this-month decision (F-6.8)."""

    snapshot = db.execute(
        select(RebalanceSnapshot).order_by(RebalanceSnapshot.run_date.desc()).limit(1)
    ).scalar_one_or_none()

    entry = TradeJournalEntry(
        snapshot_id=snapshot.id if snapshot else None,
        stock_id=None,
        action_type=ActionType.SKIP_MONTH,
        action_date=date.today(),
        user_notes=body.reason,
        executed=True,
    )
    db.add(entry)
    db.commit()
    return {"id": entry.id, "status": "skipped", "reason": body.reason}


@router.get("/refresh-prices", response_model=RefreshPricesResponse)
def refresh_prices(db: Session = Depends(get_db)) -> RefreshPricesResponse:
    """Pull 15-min delayed quotes for the current action list (F-6.7)."""
    from pipeline.providers.registry import get_data_provider

    snapshot = db.execute(
        select(RebalanceSnapshot).order_by(RebalanceSnapshot.run_date.desc()).limit(1)
    ).scalar_one_or_none()

    if snapshot is None:
        return RefreshPricesResponse(updated={}, as_of=datetime.now(tz=timezone.utc).isoformat())

    # Get tickers in current action list (top ranked + held)
    score_rows = db.execute(
        select(Score)
        .options(selectinload(Score.stock))
        .where(Score.snapshot_id == snapshot.id, Score.rank.is_not(None))
    ).scalars().all()

    tickers = list({s.stock.ticker for s in score_rows})
    provider = get_data_provider()
    updated: dict[str, float] = {}

    for ticker in tickers[:30]:   # cap at 30 (free tier safe)
        try:
            quote = provider.prices(ticker)
            if quote and not quote.empty:
                updated[ticker] = float(quote["close"].iloc[-1])
        except Exception:  # noqa: BLE001
            pass

    return RefreshPricesResponse(
        updated=updated,
        as_of=datetime.now(tz=timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_action_rows(
    score_rows: list[Score],
    holdings: list[Holding],
    snapshot: RebalanceSnapshot,
    db: Session,
) -> list[ActionRow]:
    """Reconstruct the stored diff including BUY / SELL / ADD / HOLD."""

    price_map = _latest_price_map(
        {score_row.stock_id for score_row in score_rows} | {holding.stock_id for holding in holdings},
        db,
    )
    holding_map = _holding_contexts(holdings, price_map)
    executed_keys = _executed_action_keys(snapshot.id, db)
    rows: list[ActionRow] = []

    grouped_scores: dict[tuple[Bucket, Country], list[Score]] = defaultdict(list)
    for score_row in score_rows:
        grouped_scores[(Bucket(score_row.bucket), Country(score_row.stock.country))].append(score_row)

    for (bucket, country), group_scores in grouped_scores.items():
        ranked = sorted(
            [score_row for score_row in group_scores if score_row.rank is not None],
            key=lambda score_row: score_row.rank or 0,
        )
        cutoff = ranked[-1].score if ranked else 0.0
        top_tickers = {score_row.stock.ticker for score_row in ranked}
        score_by_ticker = {score_row.stock.ticker: score_row for score_row in group_scores}
        country_holdings = {
            ticker: holding for ticker, holding in holding_map.items() if holding["country"] == country
        }

        for score_row in ranked:
            stock = score_row.stock
            holding = country_holdings.get(stock.ticker)
            current_price = price_map.get(stock.id)
            current_value = holding["current_value"] if holding else None
            action = ActionType.BUY
            reason = _score_reason(score_row, stock)

            if holding is not None:
                action = ActionType.ADD if _is_underweight(holding, len(top_tickers)) else ActionType.HOLD
                if action == ActionType.ADD:
                    reason = f"Underweight vs equal-weight target. {reason}"
                else:
                    reason = f"In top list and position is adequate. {reason}"

            rows.append(
                ActionRow(
                    ticker=stock.ticker,
                    country=country,
                    bucket=bucket,
                    action=action,
                    score=score_row.score,
                    rank=score_row.rank,
                    current_qty=holding["qty"] if holding else None,
                    current_value=current_value,
                    current_price=current_price,
                    suggested_amount=None,
                    suggested_qty=None,
                    reason=reason,
                    factor_scores=score_row.factor_scores or {},
                    executed=_action_key(stock.ticker, bucket) in executed_keys,
                )
            )

        for ticker, holding in country_holdings.items():
            if ticker in top_tickers:
                continue

            stock_score = score_by_ticker.get(ticker)
            score_value = stock_score.score if stock_score else 0.0
            drop = cutoff - score_value
            action = ActionType.SELL if drop > HYSTERESIS_BUFFER else ActionType.HOLD
            reason = (
                f"Dropped out of top list. Score {score_value:.1f} is "
                f"{drop:.1f} pts below cutoff ({cutoff:.1f})."
                if action == ActionType.SELL
                else f"Not in top list but within hysteresis buffer ({drop:.1f} pts below cutoff)."
            )

            rows.append(
                ActionRow(
                    ticker=ticker,
                    country=country,
                    bucket=bucket,
                    action=action,
                    score=score_value,
                    rank=stock_score.rank if stock_score else None,
                    current_qty=holding["qty"],
                    current_value=holding["current_value"],
                    current_price=holding["current_price"],
                    suggested_amount=None,
                    suggested_qty=None,
                    reason=reason,
                    factor_scores=(stock_score.factor_scores or {}) if stock_score else {},
                    executed=_action_key(ticker, bucket) in executed_keys,
                )
            )

    return rows


def _action_key(ticker: str, bucket: Bucket) -> str:
    return f"{ticker}|{bucket}"


def _executed_action_keys(snapshot_id: int, db: Session) -> set[str]:
    rows = db.execute(
        select(TradeJournalEntry.stock_id, TradeJournalEntry.bucket)
        .where(
            TradeJournalEntry.snapshot_id == snapshot_id,
            TradeJournalEntry.executed.is_(True),
            TradeJournalEntry.stock_id.is_not(None),
            TradeJournalEntry.bucket.is_not(None),
            TradeJournalEntry.action_type != ActionType.SKIP_MONTH,
        )
    ).all()
    if not rows:
        return set()

    stock_ids = {stock_id for stock_id, _ in rows if stock_id is not None}
    stocks = db.execute(select(Stock.id, Stock.ticker).where(Stock.id.in_(stock_ids))).all()
    ticker_by_id = {stock_id: ticker for stock_id, ticker in stocks}
    return {
        _action_key(ticker_by_id[stock_id], Bucket(bucket))
        for stock_id, bucket in rows
        if stock_id in ticker_by_id and bucket is not None
    }


def _latest_price_map(stock_ids: set[int], db: Session) -> dict[int, float]:
    if not stock_ids:
        return {}

    price_rows = db.execute(
        select(Price.stock_id, Price.close)
        .where(Price.stock_id.in_(stock_ids))
        .order_by(Price.stock_id, Price.date.desc())
    ).all()

    latest: dict[int, float] = {}
    for stock_id, close in price_rows:
        latest.setdefault(stock_id, close)
    return latest


def _holding_contexts(holdings: list[Holding], price_map: dict[int, float]) -> dict[str, dict]:
    contexts: dict[str, dict] = {}
    portfolio_total = 0.0

    for holding in holdings:
        current_price = price_map.get(holding.stock_id) or holding.avg_buy_price
        current_value = holding.quantity * current_price
        portfolio_total += current_value
        contexts[holding.stock.ticker] = {
            "id": holding.id,
            "stock_id": holding.stock_id,
            "country": Country(holding.stock.country),
            "qty": holding.quantity,
            "avg_buy_price": holding.avg_buy_price,
            "current_price": current_price,
            "current_value": current_value,
        }

    for context in contexts.values():
        context["portfolio_total"] = portfolio_total

    return contexts


def _is_underweight(holding: dict, top_count: int) -> bool:
    if top_count <= 0:
        return False
    portfolio_total = holding.get("portfolio_total")
    current_value = holding.get("current_value")
    if portfolio_total is None or current_value is None or portfolio_total <= 0:
        return False
    equal_weight_value = portfolio_total / top_count
    return current_value < equal_weight_value * UNDERWEIGHT_THRESHOLD


def _load_bucket_allocation(
    db: Session,
    *,
    bucket_alloc_quality_value: float | None,
    bucket_alloc_momentum: float | None,
    bucket_alloc_quality_momentum: float | None,
    bucket_alloc_dividend_growth: float | None,
) -> dict[Bucket, float]:
    explicit = {
        Bucket.QUALITY_VALUE: bucket_alloc_quality_value,
        Bucket.MOMENTUM: bucket_alloc_momentum,
        Bucket.QUALITY_MOMENTUM: bucket_alloc_quality_momentum,
        Bucket.DIVIDEND_GROWTH: bucket_alloc_dividend_growth,
    }
    if any(value is not None for value in explicit.values()):
        return {
            bucket: (value or 0.0) / 100.0
            for bucket, value in explicit.items()
        }

    rows = db.execute(
        select(SettingKV).where(
            SettingKV.key.in_(
                [
                    "bucket_alloc_quality_value",
                    "bucket_alloc_quality_momentum",
                    "bucket_alloc_momentum",
                    "bucket_alloc_dividend_growth",
                ]
            )
        )
    ).scalars().all()
    kv = {row.key: row.value for row in rows}
    return {
        Bucket.QUALITY_VALUE: float(kv.get("bucket_alloc_quality_value", DEFAULT_BUCKET_ALLOCATION[Bucket.QUALITY_VALUE] * 100)) / 100.0,
        Bucket.QUALITY_MOMENTUM: float(kv.get("bucket_alloc_quality_momentum", DEFAULT_BUCKET_ALLOCATION[Bucket.QUALITY_MOMENTUM] * 100)) / 100.0,
        Bucket.MOMENTUM: float(kv.get("bucket_alloc_momentum", DEFAULT_BUCKET_ALLOCATION[Bucket.MOMENTUM] * 100)) / 100.0,
        Bucket.DIVIDEND_GROWTH: float(kv.get("bucket_alloc_dividend_growth", DEFAULT_BUCKET_ALLOCATION[Bucket.DIVIDEND_GROWTH] * 100)) / 100.0,
    }


def _apply_capital_plan(action_rows: list[ActionRow], action_amounts: dict[str, float]) -> None:
    for row in action_rows:
        key = _action_key(row.ticker, row.bucket)
        amount = action_amounts.get(key)
        row.suggested_amount = amount
        if amount is not None and row.current_price and row.current_price > 0:
            row.suggested_qty = amount / row.current_price


def _apply_execution_to_holding(db: Session, stock: Stock, body: ExecuteRequest) -> None:
    holding = db.execute(select(Holding).where(Holding.stock_id == stock.id)).scalar_one_or_none()

    if body.action in (ActionType.BUY, ActionType.ADD):
        if holding is None:
            holding = Holding(
                stock_id=stock.id,
                quantity=body.qty,
                avg_buy_price=body.actual_fill_price,
                buy_date=date.today(),
                broker=_default_broker(Country(stock.country)),
            )
            db.add(holding)
            db.flush()
            return

        total_cost = holding.quantity * holding.avg_buy_price + body.qty * body.actual_fill_price
        holding.quantity += body.qty
        holding.avg_buy_price = total_cost / holding.quantity
        holding.buy_date = min(holding.buy_date, date.today())
        return

    if holding is None:
        raise HTTPException(status_code=400, detail="No holding exists for this stock")
    if body.qty > holding.quantity:
        raise HTTPException(status_code=400, detail="Executed quantity exceeds current holding")

    remaining = holding.quantity - body.qty
    if remaining <= 0:
        db.delete(holding)
    else:
        holding.quantity = remaining


def _default_broker(country: Country) -> Broker:
    return Broker.KITE if country == Country.INDIA else Broker.VESTED


def _score_reason(score_row: Score | None, stock: Stock) -> str | None:
    if score_row is None:
        return None
    return _format_reason(
        ScoreOutput(
            ticker=stock.ticker,
            bucket=Bucket(score_row.bucket),
            score=score_row.score,
            qualified=score_row.qualified,
            factor_scores=score_row.factor_scores or {},
            rank=score_row.rank,
        )
    )


def _suggested_price_for_score(score_row: Score | None) -> float | None:
    if score_row is None or not score_row.snapshot_data:
        return None
    price = score_row.snapshot_data.get("current_price")
    return float(price) if price is not None else None
