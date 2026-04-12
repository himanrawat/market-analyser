"""PortfolioDiff: compares this month's ranked lists against current holdings.

Implements F-6.2 / F-6.3 diff logic:
  In top-N + already own = HOLD (or ADD if underweight vs equal-weight target)
  In top-N + don't own   = BUY
  Not in top-N + own + score dropped > 10 pts below cutoff = SELL
  Not in top-N + own + score still close to cutoff          = HOLD (hysteresis)

Also handles F-6.4 capital deployment and F-6.5 bucket allocation sliders.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from loguru import logger
from sqlalchemy import select

from pipeline.db.base import get_session
from pipeline.db.enums import ActionType, Bucket, Country
from pipeline.db.models import Holding, Score, Stock
from pipeline.scoring.base import ScoreOutput
from pipeline.scoring.guardrails import GuardrailResult, HYSTERESIS_BUFFER

# Equal-weight tolerance: if holding value is <70% of equal-weight target → ADD
UNDERWEIGHT_THRESHOLD = 0.70


@dataclass
class ActionRow:
    """One row in the action table shown on the 7th-of-month screen."""

    ticker: str
    country: Country
    bucket: Bucket
    action: ActionType
    score: float
    rank: int | None

    # Holdings info (None if not currently held)
    current_qty: float | None = None
    current_value: float | None = None  # at latest known price

    # Suggested trade
    suggested_amount: float | None = None  # INR or USD
    suggested_qty: float | None = None

    # Explainability
    reason: str = ""
    factor_scores: dict = field(default_factory=dict)

    # UI state
    executed: bool = False

    @property
    def action_key(self) -> str:
        return f"{self.ticker}|{self.bucket}"


@dataclass
class DiffResult:
    """Complete action table for one rebalance run."""

    run_date: date
    actions: list[ActionRow]
    macro_regime: str
    shock_regime: bool

    @property
    def buys(self) -> list[ActionRow]:
        return [a for a in self.actions if a.action == ActionType.BUY]

    @property
    def sells(self) -> list[ActionRow]:
        return [a for a in self.actions if a.action == ActionType.SELL]

    @property
    def adds(self) -> list[ActionRow]:
        return [a for a in self.actions if a.action == ActionType.ADD]

    @property
    def holds(self) -> list[ActionRow]:
        return [a for a in self.actions if a.action == ActionType.HOLD]


class PortfolioDiff:
    """Generates the action table by diffing ranked lists against holdings."""

    def __init__(self, as_of: date | None = None) -> None:
        self.as_of = as_of or date.today()

    def run(self, guardrail_results: list[GuardrailResult]) -> DiffResult:
        """Produce the full action table from all guardrail results."""
        holdings = self._load_holdings()
        held_tickers = {h["ticker"] for h in holdings}
        holding_by_ticker = {h["ticker"]: h for h in holdings}

        actions: list[ActionRow] = []

        for gr in guardrail_results:
            top_tickers = {s.ticker for s in gr.ranked}
            cutoff = gr.ranked[-1].score if gr.ranked else 0.0

            # Stocks in the top-N list
            for score_out in gr.ranked:
                action = self._action_for_top_n(
                    score_out, holding_by_ticker, top_tickers
                )
                actions.append(action)

            # Held stocks NOT in the top-N — check if SELL or HOLD
            for ticker in held_tickers:
                if ticker in top_tickers:
                    continue  # already handled above
                holding = holding_by_ticker[ticker]
                # Find this stock's score in the guardrail result (may be absent)
                stock_score = self._find_score(ticker, gr.bucket, guardrail_results)
                action = self._action_for_held_not_in_list(
                    ticker, holding, gr.bucket, gr.country, stock_score, cutoff
                )
                if action:
                    actions.append(action)

        macro_regime = guardrail_results[0].macro_regime if guardrail_results else "risk_on"
        shock = guardrail_results[0].shock_regime if guardrail_results else False

        logger.info(
            f"Diff complete: {len([a for a in actions if a.action == ActionType.BUY])} BUY, "
            f"{len([a for a in actions if a.action == ActionType.SELL])} SELL, "
            f"{len([a for a in actions if a.action == ActionType.ADD])} ADD, "
            f"{len([a for a in actions if a.action == ActionType.HOLD])} HOLD"
        )
        return DiffResult(
            run_date=self.as_of,
            actions=actions,
            macro_regime=str(macro_regime),
            shock_regime=shock,
        )

    # ------------------------------------------------------------------
    # Action logic
    # ------------------------------------------------------------------

    def _action_for_top_n(
        self,
        score_out: ScoreOutput,
        holding_by_ticker: dict,
        top_tickers: set[str],
    ) -> ActionRow:
        holding = holding_by_ticker.get(score_out.ticker)
        country = self._ticker_country(score_out.ticker)

        if holding is None:
            return ActionRow(
                ticker=score_out.ticker,
                country=country,
                bucket=score_out.bucket,
                action=ActionType.BUY,
                score=score_out.score,
                rank=score_out.rank,
                reason=_format_reason(score_out),
                factor_scores=score_out.factor_scores,
            )

        # Held and in top-N: HOLD unless significantly underweight → ADD
        if self._is_underweight(holding, top_tickers):
            return ActionRow(
                ticker=score_out.ticker,
                country=country,
                bucket=score_out.bucket,
                action=ActionType.ADD,
                score=score_out.score,
                rank=score_out.rank,
                current_qty=holding["qty"],
                current_value=holding["current_value"],
                reason=f"Underweight vs equal-weight target. {_format_reason(score_out)}",
                factor_scores=score_out.factor_scores,
            )

        return ActionRow(
            ticker=score_out.ticker,
            country=country,
            bucket=score_out.bucket,
            action=ActionType.HOLD,
            score=score_out.score,
            rank=score_out.rank,
            current_qty=holding["qty"],
            current_value=holding["current_value"],
            reason="In top list and position is adequate.",
            factor_scores=score_out.factor_scores,
        )

    def _action_for_held_not_in_list(
        self,
        ticker: str,
        holding: dict,
        bucket: Bucket,
        country: Country,
        stock_score: ScoreOutput | None,
        cutoff: float,
    ) -> ActionRow | None:
        score_val = stock_score.score if stock_score else 0.0
        drop = cutoff - score_val

        if drop > HYSTERESIS_BUFFER:
            return ActionRow(
                ticker=ticker,
                country=country,
                bucket=bucket,
                action=ActionType.SELL,
                score=score_val,
                rank=None,
                current_qty=holding["qty"],
                current_value=holding["current_value"],
                reason=(
                    f"Dropped out of top list. Score {score_val:.1f} is "
                    f"{drop:.1f} pts below cutoff ({cutoff:.1f})."
                ),
            )

        # Within hysteresis buffer → HOLD (don't churn)
        return ActionRow(
            ticker=ticker,
            country=country,
            bucket=bucket,
            action=ActionType.HOLD,
            score=score_val,
            rank=None,
            current_qty=holding["qty"],
            current_value=holding["current_value"],
            reason=(
                f"Not in top list but within hysteresis buffer "
                f"({drop:.1f} pts below cutoff)."
            ),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_underweight(self, holding: dict, top_tickers: set[str]) -> bool:
        """True if holding value is < UNDERWEIGHT_THRESHOLD × equal-weight target."""
        if holding["current_value"] is None or holding["portfolio_total"] is None:
            return False
        n = len(top_tickers)
        if n == 0:
            return False
        equal_weight_value = holding["portfolio_total"] / n
        return holding["current_value"] < equal_weight_value * UNDERWEIGHT_THRESHOLD

    def _find_score(
        self, ticker: str, bucket: Bucket, all_results: list[GuardrailResult]
    ) -> ScoreOutput | None:
        for gr in all_results:
            if gr.bucket != bucket:
                continue
            for s in gr.ranked + gr.extended:
                if s.ticker == ticker:
                    return s
        return None

    def _ticker_country(self, ticker: str) -> Country:
        with get_session() as session:
            row = session.execute(
                select(Stock.country).where(Stock.ticker == ticker)
            ).scalar_one_or_none()
        return Country(row) if row else Country.US

    def _load_holdings(self) -> list[dict]:
        """Load current holdings with current_value computed from latest price."""
        with get_session() as session:
            rows = session.execute(
                select(
                    Stock.ticker,
                    Stock.country,
                    Holding.quantity,
                    Holding.avg_buy_price,
                )
                .join(Stock, Holding.stock_id == Stock.id)
            ).all()

        if not rows:
            return []

        # Compute current value using latest price in DB
        from pipeline.db.models import Price
        holdings = []
        portfolio_total = 0.0
        for row in rows:
            with get_session() as session:
                latest_price = session.execute(
                    select(Price.close)
                    .join(Stock, Price.stock_id == Stock.id)
                    .where(Stock.ticker == row.ticker)
                    .order_by(Price.date.desc())
                    .limit(1)
                ).scalar_one_or_none()

            current_price = latest_price or row.avg_buy_price
            current_value = row.quantity * current_price
            portfolio_total += current_value
            holdings.append({
                "ticker": row.ticker,
                "country": row.country,
                "qty": row.quantity,
                "avg_buy_price": row.avg_buy_price,
                "current_price": current_price,
                "current_value": current_value,
                "portfolio_total": None,  # filled in below
            })

        for h in holdings:
            h["portfolio_total"] = portfolio_total
        return holdings


def _format_reason(s: ScoreOutput) -> str:
    """Build a short plain-English reason from the top scoring factors (F-7.9)."""
    if not s.factor_scores:
        return f"Score: {s.score:.1f}"
    top = sorted(s.factor_scores.items(), key=lambda x: x[1], reverse=True)[:3]
    factors = ", ".join(f"{k.replace('_', ' ')} ({v:.1f})" for k, v in top)
    return f"Score {s.score:.1f}. Top factors: {factors}."
