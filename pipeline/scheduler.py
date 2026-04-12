"""Monthly pipeline orchestrator (F-12.4).

Designed to be called by cron on the 6th of each month:

  0 20 6 * * /path/to/.venv/bin/python -m pipeline.scheduler

Can also be invoked manually:
  python -m pipeline.scheduler

What it does (in order):
  1. Universe refresh — upsert Nifty 500 + S&P 500 constituents
  2. Data pull — prices, fundamentals, macro snapshot (via DataProvider)
  3. Universe filter — apply F-2.x hard filters
  4. Scoring — run all 4 bucket scorers
  5. Guardrails — sector cap, earnings blackout, hysteresis, macro regime
  6. Portfolio diff — BUY/SELL/ADD/HOLD action table
  7. Capital planner — split fresh capital across BUY/ADD actions
  8. Shock check — apply auto-Risk-Off override if RED event in last 14 days
  9. Persist snapshot — write DiffResult to RebalanceSnapshot + Score rows
 10. Telegram digest — send monthly summary

Each step is logged. If any step raises an uncaught exception the run aborts
and a Telegram error alert is sent so the failure is visible immediately.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone

from loguru import logger

from pipeline.config import settings
from pipeline.db import init_db
from pipeline.db.base import get_session
from pipeline.db.enums import ActionType, Bucket, Country
from pipeline.db.models import RebalanceSnapshot, Score
from pipeline.logging_setup import configure_logging
from pipeline.news.shock import ShockDetector
from pipeline.notify.telegram import TelegramNotifier
from pipeline.portfolio.diff import PortfolioDiff
from pipeline.portfolio.planner import CapitalPlanner
from pipeline.providers.registry import get_data_provider
from pipeline.scoring.engine import ScoringEngine
from pipeline.scoring.guardrails import Guardrails
from pipeline.universe.loader import UniverseLoader


def run_pipeline(
    as_of: date | None = None,
    fresh_capital: float = 0.0,
    picks_per_bucket: int = 10,
) -> None:
    """Execute the full monthly pipeline.

    Args:
        as_of: Override run date (default: today).
        fresh_capital: Amount in home currency to deploy across BUY/ADD actions.
        picks_per_bucket: Top-N stocks per bucket (default 10).
    """
    run_date = as_of or date.today()
    configure_logging()
    notifier = TelegramNotifier()

    logger.info("=" * 60)
    logger.info(f"Pipeline run starting — {run_date}")
    logger.info("=" * 60)

    try:
        # Step 1 — ensure DB is initialised
        init_db()

        # Step 2 — universe refresh
        logger.info("Step 1/8: Refreshing universe...")
        loader = UniverseLoader()
        loader.refresh()

        # Step 3 — data pull is handled lazily by ScoringEngine via DataProvider;
        # we prime the macro snapshot here so guardrails has fresh VIX data.
        logger.info("Step 2/8: Pulling macro snapshot...")
        provider = get_data_provider()
        _pull_macro(provider)

        # Step 4+5 — scoring
        logger.info("Step 3/8: Running scoring engine...")
        engine = ScoringEngine(as_of=run_date)
        score_outputs = engine.run(picks_per_bucket=picks_per_bucket)

        # Step 6 — guardrails
        logger.info("Step 4/8: Applying guardrails...")
        guardrails = Guardrails(picks_per_bucket=picks_per_bucket, as_of=run_date)
        guardrail_results = guardrails.run(score_outputs)

        # Step 7 — shock auto-Risk-Off override
        logger.info("Step 5/8: Checking shock regime...")
        detector = ShockDetector()
        active = detector.active_shock(within_days=14)
        if active:
            logger.warning(
                f"Active RED shock event found (triggered {active.triggered_at}). "
                "Auto-Risk-Off override applied."
            )
            for gr in guardrail_results:
                gr.shock_regime = True

        # Step 8 — portfolio diff
        logger.info("Step 6/8: Computing portfolio diff...")
        diff = PortfolioDiff(as_of=run_date)
        diff_result = diff.run(guardrail_results)

        # Step 9 — capital planner
        logger.info("Step 7/8: Running capital planner...")
        planner = CapitalPlanner()
        plan = planner.plan(diff_result.buys + diff_result.adds, fresh_capital=fresh_capital)
        logger.info(
            f"Capital plan: total={plan.total_available:.0f}, "
            f"deployed={sum(plan.action_amounts.values()):.0f}, "
            f"undeployed={plan.undeployed:.0f}"
        )

        # Step 10 — persist snapshot
        logger.info("Step 8/8: Persisting snapshot...")
        _persist_snapshot(diff_result, guardrail_results, run_date)

        # Step 11 — Telegram digest
        notifier.send_monthly_digest(diff_result)

        logger.info("=" * 60)
        logger.info(
            f"Pipeline complete — "
            f"{len(diff_result.buys)} BUY, "
            f"{len(diff_result.sells)} SELL, "
            f"{len(diff_result.adds)} ADD, "
            f"{len(diff_result.holds)} HOLD"
        )
        logger.info("=" * 60)

    except Exception as exc:
        logger.exception(f"Pipeline failed: {exc}")
        notifier.send_text(
            f"❌ <b>Pipeline run FAILED</b> — {run_date}\n\n"
            f"Error: {type(exc).__name__}: {exc}\n\n"
            "Check server logs for full traceback."
        )
        sys.exit(1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pull_macro(provider) -> None:
    """Pull a small set of macro indicators to warm the cache."""
    indicators = [
        "US_VIX", "INDIA_VIX", "SPX_INDEX", "NIFTY_INDEX",
        "US_10Y_YIELD", "USD_INR",
    ]
    for name in indicators:
        try:
            provider.macro(name)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Could not fetch macro indicator {name}: {exc}")


def _persist_snapshot(diff_result, guardrail_results, run_date: date) -> None:
    """Write RebalanceSnapshot and Score rows for the audit trail."""
    from pipeline.db.enums import MacroRegime

    macro_regime_str = guardrail_results[0].macro_regime if guardrail_results else "risk_on"
    shock = any(gr.shock_regime for gr in guardrail_results)

    with get_session() as session:
        snapshot = RebalanceSnapshot(
            run_date=run_date,
            macro_regime=str(macro_regime_str),
            shock_regime=shock,
            picks_per_bucket=len(guardrail_results[0].ranked) if guardrail_results else 0,
        )
        session.add(snapshot)
        session.flush()  # get snapshot.id

        for gr in guardrail_results:
            for score_out in gr.ranked + gr.extended:
                score_row = Score(
                    snapshot_id=snapshot.id,
                    ticker=score_out.ticker,
                    bucket=score_out.bucket,
                    score=score_out.score,
                    rank=score_out.rank,
                    qualified=score_out.qualified,
                    factor_scores=score_out.factor_scores,
                )
                session.add(score_row)

        session.commit()
    logger.info(f"Snapshot {snapshot.id} persisted for {run_date}.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run the monthly rebalance pipeline.")
    parser.add_argument("--fresh-capital", type=float, default=0.0,
                        help="Fresh capital to deploy (INR or USD)")
    parser.add_argument("--picks", type=int, default=10,
                        help="Stocks per bucket (default 10)")
    parser.add_argument("--date", type=str, default=None,
                        help="Override run date YYYY-MM-DD (default: today)")
    args = parser.parse_args()

    run_date_arg = date.fromisoformat(args.date) if args.date else None
    run_pipeline(
        as_of=run_date_arg,
        fresh_capital=args.fresh_capital,
        picks_per_bucket=args.picks,
    )
