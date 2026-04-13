"""CapitalPlanner: splits fresh capital + SELL proceeds across BUY/ADD actions.

Implements F-6.4 (capital deployment) and F-6.5 (bucket allocation sliders).

Default bucket allocation (F-6.5):
  Quality+Value     60%
  Quality+Momentum  40%
  Momentum           0%
  Dividend Growth    0%
"""
from __future__ import annotations

from dataclasses import dataclass

from pipeline.db.enums import ActionType, Bucket
from pipeline.portfolio.diff import ActionRow

DEFAULT_BUCKET_ALLOCATION: dict[Bucket, float] = {
    Bucket.QUALITY_VALUE: 0.60,
    Bucket.QUALITY_MOMENTUM: 0.40,
    Bucket.MOMENTUM: 0.00,
    Bucket.DIVIDEND_GROWTH: 0.00,
}


@dataclass
class DeploymentPlan:
    """Output of CapitalPlanner.plan()."""

    total_available: float              # fresh_capital + sell_proceeds
    bucket_allocations: dict[Bucket, float]  # bucket → amount allocated
    action_amounts: dict[str, float]    # "<ticker>|<country>|<bucket>" → suggested amount
    undeployed: float                   # leftover if no BUY/ADD in a bucket


class CapitalPlanner:
    """Splits capital across buckets and BUY/ADD actions within each bucket."""

    def __init__(
        self,
        bucket_allocation: dict[Bucket, float] | None = None,
    ) -> None:
        alloc = bucket_allocation or DEFAULT_BUCKET_ALLOCATION
        total = sum(alloc.values())
        # Normalise to 1.0 in case user entered percentages that don't sum exactly
        self._alloc = {b: v / total for b, v in alloc.items()} if total > 0 else alloc

    def plan(
        self,
        actions: list[ActionRow],
        fresh_capital: float,
        sell_proceeds: float = 0.0,
    ) -> DeploymentPlan:
        """Distribute total = fresh_capital + sell_proceeds across BUY/ADD actions."""
        total = fresh_capital + sell_proceeds
        bucket_amounts: dict[Bucket, float] = {
            b: total * pct for b, pct in self._alloc.items()
        }

        # Group BUY and ADD actions by bucket
        by_bucket: dict[Bucket, list[ActionRow]] = {b: [] for b in Bucket}
        for action in actions:
            if action.action in (ActionType.BUY, ActionType.ADD):
                by_bucket[action.bucket].append(action)

        action_amounts: dict[str, float] = {}
        undeployed = 0.0

        for bucket, budget in bucket_amounts.items():
            active_actions = by_bucket[bucket]
            if not active_actions:
                undeployed += budget
                continue
            # Equal split within the bucket
            per_action = budget / len(active_actions)
            for action in active_actions:
                action_amounts[action.action_key] = per_action
                action.suggested_amount = per_action

        return DeploymentPlan(
            total_available=total,
            bucket_allocations=bucket_amounts,
            action_amounts=action_amounts,
            undeployed=undeployed,
        )
