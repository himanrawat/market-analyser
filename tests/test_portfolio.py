"""Tests for portfolio diff engine and capital planner."""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from pipeline.db.enums import ActionType, Bucket, Country, MacroRegime
from pipeline.portfolio.diff import ActionRow, DiffResult, PortfolioDiff, _format_reason
from pipeline.portfolio.planner import CapitalPlanner, DEFAULT_BUCKET_ALLOCATION, DeploymentPlan
from pipeline.scoring.base import ScoreOutput
from pipeline.scoring.guardrails import GuardrailResult

pytestmark = pytest.mark.us


def _score(ticker: str, score: float, rank: int = 1, bucket=Bucket.QUALITY_MOMENTUM) -> ScoreOutput:
    return ScoreOutput(
        ticker=ticker, country=Country.US, bucket=bucket, score=score, qualified=True,
        factor_scores={"roe_5yr_avg": 15.0, "momentum_12m_1m": 18.0},
        rank=rank,
    )


def _gr(ranked: list[ScoreOutput], country=Country.US, bucket=Bucket.QUALITY_MOMENTUM) -> GuardrailResult:
    return GuardrailResult(
        bucket=bucket, country=country,
        ranked=ranked, extended=[],
        macro_regime=MacroRegime.RISK_ON, shock_regime=False,
        removed_by_blackout=[], removed_by_sector_cap=[],
    )


def _holding(ticker: str, qty=10.0, avg_price=100.0, current_value=1000.0, portfolio_total=10000.0):
    return {
        "ticker": ticker,
        "country": Country.US,
        "qty": qty,
        "avg_buy_price": avg_price,
        "current_price": current_value / qty,
        "current_value": current_value,
        "portfolio_total": portfolio_total,
    }


class TestPortfolioDiff:
    @pytest.fixture()
    def diff(self):
        d = PortfolioDiff(as_of=date(2026, 4, 7))
        return d

    def _run(self, diff, guardrail_results, holdings):
        with (
            patch.object(diff, "_load_holdings", return_value=holdings),
        ):
            return diff.run(guardrail_results)

    def test_new_stock_in_top_n_is_buy(self, diff):
        result = self._run(diff, [_gr([_score("AAPL", 85.0)])], holdings=[])
        buys = result.buys
        assert any(a.ticker == "AAPL" for a in buys)

    def test_held_stock_in_top_n_is_hold(self, diff):
        # 1 stock in top-N → equal-weight target = portfolio_total / 1 = 10000
        # current_value 9000 > 10000 * 0.70 → adequate → HOLD (not ADD)
        holding = _holding("AAPL", qty=10, current_value=9000, portfolio_total=10000)
        result = self._run(diff, [_gr([_score("AAPL", 85.0)])], holdings=[holding])
        holds = result.holds
        assert any(a.ticker == "AAPL" for a in holds)

    def test_held_stock_not_in_list_score_dropped_far_is_sell(self, diff):
        # Cutoff is 85 (from ranked[-1]). MSFT score = 60. Drop = 25 > buffer(10) → SELL
        gr = _gr([_score("AAPL", 85.0, rank=1)])
        msft_holding = _holding("MSFT", qty=5, current_value=2500)
        result = self._run(diff, [gr], holdings=[msft_holding])
        sells = result.sells
        assert any(a.ticker == "MSFT" for a in sells)

    def test_held_stock_near_cutoff_is_hold(self, diff):
        # Cutoff 85, MSFT score 78 → drop 7 < buffer(10) → HOLD
        gr = _gr([_score("AAPL", 85.0, rank=1)])
        msft_score = ScoreOutput(
            ticker="MSFT", country=Country.US, bucket=Bucket.QUALITY_MOMENTUM, score=78.0,
            qualified=False, factor_scores={}, rank=None,
        )
        gr.extended = [msft_score]
        msft_holding = _holding("MSFT")
        result = self._run(diff, [gr], holdings=[msft_holding])
        # MSFT should be HOLD, not SELL
        msft_actions = [a for a in result.actions if a.ticker == "MSFT"]
        assert all(a.action == ActionType.HOLD for a in msft_actions)

    def test_result_counts(self, diff):
        result = self._run(diff, [_gr([_score("AAPL", 90.0), _score("MSFT", 80.0)])], holdings=[])
        assert len(result.buys) == 2
        assert len(result.sells) == 0

    def test_format_reason_includes_top_factors(self):
        s = ScoreOutput(
            ticker="AAPL", country=Country.US, bucket=Bucket.QUALITY_MOMENTUM, score=82.5,
            qualified=True,
            factor_scores={"roe_5yr_avg": 15.0, "momentum_12m_1m": 18.0, "debt_equity": 8.0},
        )
        reason = _format_reason(s)
        assert "82.5" in reason
        assert "momentum 12m 1m" in reason  # underscores → spaces


class TestCapitalPlanner:
    def test_total_is_fresh_plus_proceeds(self):
        planner = CapitalPlanner()
        plan = planner.plan([], fresh_capital=15000.0, sell_proceeds=5000.0)
        assert abs(plan.total_available - 20000.0) < 1e-6

    def test_default_allocation_sums_to_total(self):
        planner = CapitalPlanner()
        actions = [
            ActionRow("AAPL", Country.US, Bucket.QUALITY_VALUE, ActionType.BUY, 80.0, 1),
            ActionRow("MSFT", Country.US, Bucket.QUALITY_MOMENTUM, ActionType.BUY, 75.0, 1),
        ]
        plan = planner.plan(actions, fresh_capital=10000.0)
        deployed = sum(plan.action_amounts.values())
        assert abs(deployed + plan.undeployed - plan.total_available) < 1e-6

    def test_qv_gets_60pct_qm_gets_40pct(self):
        planner = CapitalPlanner()
        actions = [
            ActionRow("A", Country.US, Bucket.QUALITY_VALUE, ActionType.BUY, 80.0, 1),
            ActionRow("B", Country.US, Bucket.QUALITY_MOMENTUM, ActionType.BUY, 75.0, 1),
        ]
        plan = planner.plan(actions, fresh_capital=10000.0)
        assert abs(plan.bucket_allocations[Bucket.QUALITY_VALUE] - 6000.0) < 1e-6
        assert abs(plan.bucket_allocations[Bucket.QUALITY_MOMENTUM] - 4000.0) < 1e-6

    def test_empty_bucket_goes_to_undeployed(self):
        planner = CapitalPlanner()
        # Only QM action, QV has no actions → QV budget is undeployed
        actions = [
            ActionRow("B", Country.US, Bucket.QUALITY_MOMENTUM, ActionType.BUY, 75.0, 1),
        ]
        plan = planner.plan(actions, fresh_capital=10000.0)
        assert plan.undeployed > 0

    def test_multiple_buys_in_same_bucket_split_equally(self):
        planner = CapitalPlanner()
        actions = [
            ActionRow("A", Country.US, Bucket.QUALITY_MOMENTUM, ActionType.BUY, 90.0, 1),
            ActionRow("B", Country.US, Bucket.QUALITY_MOMENTUM, ActionType.BUY, 85.0, 2),
        ]
        plan = planner.plan(actions, fresh_capital=10000.0)
        # QM gets 40% = 4000; split equally between A and B → 2000 each
        assert abs(plan.action_amounts["A|US|quality_momentum"] - 2000.0) < 1e-6
        assert abs(plan.action_amounts["B|US|quality_momentum"] - 2000.0) < 1e-6

    def test_custom_allocation_normalised(self):
        # User passes raw percentages (60, 40) — should still work
        alloc = {Bucket.QUALITY_VALUE: 70.0, Bucket.QUALITY_MOMENTUM: 30.0}
        planner = CapitalPlanner(bucket_allocation=alloc)
        actions = [
            ActionRow("A", Country.US, Bucket.QUALITY_VALUE, ActionType.BUY, 80.0, 1),
        ]
        plan = planner.plan(actions, fresh_capital=10000.0)
        assert abs(plan.bucket_allocations[Bucket.QUALITY_VALUE] - 7000.0) < 1e-6

    def test_add_actions_receive_capital(self):
        planner = CapitalPlanner()
        actions = [
            ActionRow("A", Country.US, Bucket.QUALITY_MOMENTUM, ActionType.ADD, 85.0, 2),
        ]
        plan = planner.plan(actions, fresh_capital=10000.0)
        assert "A|US|quality_momentum" in plan.action_amounts
