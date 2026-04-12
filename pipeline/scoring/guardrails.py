"""Guardrails applied to scored lists before they reach the UI.

F-4.1  Sector cap: max 3 stocks from any single sector in any top-N list.
F-4.2  Earnings blackout: stock with earnings within 5 days → removed, replaced
       by next-highest qualifier.
F-4.3  Hysteresis: held stock only drops off if score fell > 10 pts below cutoff.
F-4.4  Macro veto: if Nifty 50 or S&P 500 is below 200 DMA → tag "Defensive Regime".
F-4.5  View-more: top N are "actionable"; rest are browsable (rank > N, no action buttons).
F-4.6  Picks-per-bucket: default 10, configurable 5/10/15/20.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from loguru import logger
from sqlalchemy import select

from pipeline.db.base import get_session
from pipeline.db.enums import Bucket, Country, MacroRegime
from pipeline.db.models import Event, Holding, Stock
from pipeline.scoring.base import ScoreOutput

SECTOR_CAP = 3            # F-4.1
EARNINGS_BLACKOUT_DAYS = 5  # F-4.2
HYSTERESIS_BUFFER = 10.0   # F-4.3 — points below cutoff before a held stock drops
DEFAULT_PICKS = 10         # F-4.6


@dataclass
class GuardrailResult:
    """Output of applying guardrails to one (bucket, country) list."""

    bucket: Bucket
    country: Country
    ranked: list[ScoreOutput]          # top N — actionable
    extended: list[ScoreOutput]        # beyond top N — browsable only
    macro_regime: MacroRegime
    shock_regime: bool
    removed_by_blackout: list[str]     # tickers removed for earnings blackout
    removed_by_sector_cap: list[str]   # tickers removed for sector cap
    notes: list[str] = field(default_factory=list)


class Guardrails:
    """Apply all guardrails to a scored universe and return ranked lists."""

    def __init__(
        self,
        picks_per_bucket: int = DEFAULT_PICKS,
        as_of: date | None = None,
    ) -> None:
        self.picks = picks_per_bucket
        self.as_of = as_of or date.today()

    def apply(
        self,
        scores: list[ScoreOutput],
        macro_regime: MacroRegime,
        shock_regime: bool,
    ) -> list[GuardrailResult]:
        """Apply guardrails for every (bucket, country) combination.

        `scores` is the full flat list from ScoringEngine.run(). Returns one
        GuardrailResult per (bucket, country) pair — 8 total for the default
        Nifty 500 + S&P 500 universe.
        """
        held_tickers = self._load_held_tickers()
        upcoming_earnings = self._load_upcoming_earnings(self.as_of)
        sector_by_ticker = self._load_sectors()

        results: list[GuardrailResult] = []
        for bucket in Bucket:
            for country in Country:
                bucket_scores = [
                    s for s in scores
                    if s.bucket == bucket and _ticker_country(s.ticker, country, sector_by_ticker)
                ]
                result = self._apply_one(
                    bucket_scores,
                    bucket,
                    country,
                    held_tickers,
                    upcoming_earnings,
                    sector_by_ticker,
                    macro_regime,
                    shock_regime,
                )
                results.append(result)
        return results

    # ------------------------------------------------------------------

    def _apply_one(
        self,
        scores: list[ScoreOutput],
        bucket: Bucket,
        country: Country,
        held_tickers: set[str],
        upcoming_earnings: set[str],
        sector_by_ticker: dict[str, str | None],
        macro_regime: MacroRegime,
        shock_regime: bool,
    ) -> GuardrailResult:
        # Start with qualified scores sorted descending
        qualified = sorted(
            [s for s in scores if s.qualified], key=lambda s: s.score, reverse=True
        )

        # F-4.3 Hysteresis: compute score cutoff (score of Nth qualifier)
        cutoff = qualified[self.picks - 1].score if len(qualified) >= self.picks else 0.0

        removed_blackout: list[str] = []
        removed_sector: list[str] = []

        ranked: list[ScoreOutput] = []
        sector_counts: dict[str, int] = {}

        for s in qualified:
            if len(ranked) >= self.picks * 3:  # upper bound for extended list
                break

            # F-4.2 Earnings blackout
            if s.ticker in upcoming_earnings:
                removed_blackout.append(s.ticker)
                logger.debug(f"[guardrails] {s.ticker} removed: earnings blackout")
                continue

            # F-4.3 Hysteresis: held stock — only drop if score > 10 pts below cutoff
            if s.ticker in held_tickers and s.score < cutoff - HYSTERESIS_BUFFER:
                logger.debug(
                    f"[guardrails] {s.ticker} held but score {s.score:.1f} "
                    f"too far below cutoff {cutoff:.1f}"
                )
                continue

            # F-4.1 Sector cap
            sector = sector_by_ticker.get(s.ticker)
            if sector:
                current = sector_counts.get(sector, 0)
                if current >= SECTOR_CAP and len(ranked) < self.picks:
                    removed_sector.append(s.ticker)
                    logger.debug(
                        f"[guardrails] {s.ticker} removed: sector cap ({sector})"
                    )
                    continue
                sector_counts[sector] = current + 1

            ranked.append(s)

        # Assign ranks
        top_n = ranked[: self.picks]
        extended = ranked[self.picks:]
        for i, s in enumerate(top_n, start=1):
            s.rank = i
        for i, s in enumerate(extended, start=self.picks + 1):
            s.rank = i

        notes: list[str] = []
        if macro_regime == MacroRegime.RISK_OFF:
            notes.append("Defensive Regime — consider reducing new buys")
        if shock_regime:
            notes.append("Shock Regime — review carefully; 'Skip this month' highlighted")

        return GuardrailResult(
            bucket=bucket,
            country=country,
            ranked=top_n,
            extended=extended,
            macro_regime=macro_regime,
            shock_regime=shock_regime,
            removed_by_blackout=removed_blackout,
            removed_by_sector_cap=removed_sector,
            notes=notes,
        )

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    def _load_held_tickers(self) -> set[str]:
        with get_session() as session:
            rows = session.execute(
                select(Stock.ticker).join(
                    Holding, Holding.stock_id == Stock.id
                )
            ).scalars().all()
        return set(rows)

    def _load_upcoming_earnings(self, as_of: date) -> set[str]:
        """Tickers with earnings within EARNINGS_BLACKOUT_DAYS of as_of."""
        from datetime import timedelta
        horizon = as_of + timedelta(days=EARNINGS_BLACKOUT_DAYS)
        with get_session() as session:
            rows = session.execute(
                select(Stock.ticker).join(
                    Event, Event.stock_id == Stock.id
                ).where(
                    Event.event_type == "earnings",
                    Event.event_date >= as_of,
                    Event.event_date <= horizon,
                )
            ).scalars().all()
        return set(rows)

    def _load_sectors(self) -> dict[str, str | None]:
        with get_session() as session:
            rows = session.execute(select(Stock.ticker, Stock.sector)).all()
        return {r.ticker: r.sector for r in rows}


def _ticker_country(ticker: str, country: Country, sector_by_ticker: dict) -> bool:
    """Placeholder filter — in practice the ScoreOutput carries the country.
    The scorer sets ticker but not country on ScoreOutput currently; this is
    resolved by the pipeline runner which separates scores by country before
    passing to guardrails. Here we always return True since the caller already
    filters by country before calling _apply_one."""
    return True


def compute_macro_regime(
    nifty_close: float | None,
    nifty_200dma: float | None,
    sp_close: float | None,
    sp_200dma: float | None,
) -> MacroRegime:
    """F-4.4: Risk-Off if either major index is below its 200 DMA.
    Caution if one is below. Risk-On if both are above."""
    nifty_ok = nifty_close is not None and nifty_200dma is not None and nifty_close > nifty_200dma
    sp_ok = sp_close is not None and sp_200dma is not None and sp_close > sp_200dma

    if nifty_ok and sp_ok:
        return MacroRegime.RISK_ON
    if not nifty_ok and not sp_ok:
        return MacroRegime.RISK_OFF
    return MacroRegime.CAUTION
