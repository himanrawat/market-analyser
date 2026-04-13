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

# India-specific hard disqualifiers
INDIA_PLEDGE_MAX = 50.0    # Promoter pledge > 50% → disqualified
INDIA_PLEDGE_CAUTION = 25.0  # > 25% → caution note only, not disqualified


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
    removed_by_india_rules: list[str]  # tickers removed for F&O ban / ASM / pledge
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
        held_keys = self._load_held_keys()
        upcoming_earnings = self._load_upcoming_earnings(self.as_of)
        sector_by_key = self._load_sectors()
        india_flags = self._load_india_flags()   # {ticker: {fno_ban, asm_gsm, pledge_pct}}

        results: list[GuardrailResult] = []
        for bucket in Bucket:
            for country in Country:
                bucket_scores = [
                    s for s in scores
                    if s.bucket == bucket and s.country == country
                ]
                result = self._apply_one(
                    bucket_scores,
                    bucket,
                    country,
                    held_keys,
                    upcoming_earnings,
                    sector_by_key,
                    macro_regime,
                    shock_regime,
                    india_flags,
                )
                results.append(result)
        return results

    # ------------------------------------------------------------------

    def _apply_one(
        self,
        scores: list[ScoreOutput],
        bucket: Bucket,
        country: Country,
        held_keys: set[tuple[str, Country]],
        upcoming_earnings: set[tuple[str, Country]],
        sector_by_key: dict[tuple[str, Country], str | None],
        macro_regime: MacroRegime,
        shock_regime: bool,
        india_flags: dict[str, dict] | None = None,
    ) -> GuardrailResult:
        # Start with qualified scores sorted descending
        qualified = sorted(
            [s for s in scores if s.qualified], key=lambda s: s.score, reverse=True
        )

        # F-4.3 Hysteresis: compute score cutoff (score of Nth qualifier)
        cutoff = qualified[self.picks - 1].score if len(qualified) >= self.picks else 0.0

        removed_blackout: list[str] = []
        removed_sector: list[str] = []
        removed_india: list[str] = []   # India hard disqualifiers

        ranked: list[ScoreOutput] = []
        sector_counts: dict[str, int] = {}
        _india_flags = india_flags or {}

        for s in qualified:
            if len(ranked) >= self.picks * 3:  # upper bound for extended list
                break
            stock_key = (s.ticker, s.country)

            # India hard disqualifiers (F&O ban, ASM/GSM, excessive pledge)
            if s.country == Country.INDIA:
                flags = _india_flags.get(s.ticker, {})
                if flags.get("in_fno_ban"):
                    removed_india.append(s.ticker)
                    logger.debug(f"[guardrails] {s.ticker} removed: F&O ban")
                    s.disqualifiers.append("fno_ban")
                    continue
                if flags.get("in_asm_gsm"):
                    removed_india.append(s.ticker)
                    logger.debug(f"[guardrails] {s.ticker} removed: ASM/GSM surveillance")
                    s.disqualifiers.append("asm_gsm_surveillance")
                    continue
                pledge = flags.get("pledge_pct")
                if pledge is not None and pledge > INDIA_PLEDGE_MAX:
                    removed_india.append(s.ticker)
                    logger.debug(f"[guardrails] {s.ticker} removed: promoter pledge {pledge:.1f}%")
                    s.disqualifiers.append(f"promoter_pledge_too_high ({pledge:.0f}%)")
                    continue

            # F-4.2 Earnings blackout
            if stock_key in upcoming_earnings:
                removed_blackout.append(s.ticker)
                logger.debug(f"[guardrails] {s.ticker} removed: earnings blackout")
                continue

            # F-4.3 Hysteresis: held stock — only drop if score > 10 pts below cutoff
            if stock_key in held_keys and s.score < cutoff - HYSTERESIS_BUFFER:
                logger.debug(
                    f"[guardrails] {s.ticker} held but score {s.score:.1f} "
                    f"too far below cutoff {cutoff:.1f}"
                )
                continue

            # F-4.1 Sector cap
            sector = sector_by_key.get(stock_key)
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
        # Caution note for high-but-not-disqualifying pledge
        caution_pledge = [
            t for t, flags in _india_flags.items()
            if INDIA_PLEDGE_CAUTION < (flags.get("pledge_pct") or 0) <= INDIA_PLEDGE_MAX
            and any(s.ticker == t for s in top_n)
        ]
        if caution_pledge:
            notes.append(f"High promoter pledge caution: {', '.join(caution_pledge)}")

        return GuardrailResult(
            bucket=bucket,
            country=country,
            ranked=top_n,
            extended=extended,
            macro_regime=macro_regime,
            shock_regime=shock_regime,
            removed_by_blackout=removed_blackout,
            removed_by_sector_cap=removed_sector,
            removed_by_india_rules=removed_india,
            notes=notes,
        )

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    def _load_held_keys(self) -> set[tuple[str, Country]]:
        with get_session() as session:
            rows = session.execute(
                select(Stock.ticker, Stock.country).join(
                    Holding, Holding.stock_id == Stock.id
                )
            ).all()
        return {(row.ticker, Country(row.country)) for row in rows}

    def _load_upcoming_earnings(self, as_of: date) -> set[tuple[str, Country]]:
        """Tickers with earnings within EARNINGS_BLACKOUT_DAYS of as_of."""
        from datetime import timedelta
        horizon = as_of + timedelta(days=EARNINGS_BLACKOUT_DAYS)
        with get_session() as session:
            rows = session.execute(
                select(Stock.ticker, Stock.country).join(
                    Event, Event.stock_id == Stock.id
                ).where(
                    Event.event_type == "earnings",
                    Event.event_date >= as_of,
                    Event.event_date <= horizon,
                )
            ).all()
        return {(row.ticker, Country(row.country)) for row in rows}

    def _load_sectors(self) -> dict[tuple[str, Country], str | None]:
        with get_session() as session:
            rows = session.execute(select(Stock.ticker, Stock.country, Stock.sector)).all()
        return {(row.ticker, Country(row.country)): row.sector for row in rows}

    def _load_india_flags(self) -> dict[str, dict]:
        """Return {ticker: {in_fno_ban, in_asm_gsm, pledge_pct}} for India stocks.

        F&O ban and ASM/GSM flags come from the stocks table (boolean columns set
        during pipeline sync).  Pledge comes from the most-recent fundamental row.
        """
        from pipeline.db.models import Fundamental

        flags: dict[str, dict] = {}

        with get_session() as session:
            # F&O ban and ASM/GSM flags on the Stock row
            stock_rows = session.execute(
                select(Stock.ticker, Stock.in_fno_ban, Stock.in_asm_gsm).where(
                    Stock.country == Country.INDIA.value
                )
            ).all()
            for row in stock_rows:
                flags[row.ticker] = {
                    "in_fno_ban": bool(row.in_fno_ban),
                    "in_asm_gsm": bool(row.in_asm_gsm),
                    "pledge_pct": None,
                }

            # Promoter pledge from most-recent fundamental row per stock
            pledge_rows = session.execute(
                select(Stock.ticker, Fundamental.promoter_pledge_pct)
                .join(Fundamental, Fundamental.stock_id == Stock.id)
                .where(Stock.country == Country.INDIA.value)
                .order_by(Fundamental.fiscal_date.desc())
            ).all()
            seen: set[str] = set()
            for row in pledge_rows:
                if row.ticker not in seen:
                    seen.add(row.ticker)
                    if row.ticker not in flags:
                        flags[row.ticker] = {"in_fno_ban": False, "in_asm_gsm": False}
                    flags[row.ticker]["pledge_pct"] = row.promoter_pledge_pct

        return flags


def compute_macro_regime(
    nifty_close: float | None,
    nifty_200dma: float | None,
    _sp_close: float | None = None,  # reserved for Phase 2 (US market)
    _sp_200dma: float | None = None,  # reserved for Phase 2 (US market)
) -> MacroRegime:
    """F-4.4: Regime determined by Nifty 50 vs its 200 DMA (India-only, Phase 1).
    Phase 2 will re-add S&P 500 cross-check."""
    nifty_ok = nifty_close is not None and nifty_200dma is not None and nifty_close > nifty_200dma

    if nifty_ok:
        return MacroRegime.RISK_ON
    if nifty_close is None or nifty_200dma is None:
        return MacroRegime.CAUTION
    return MacroRegime.RISK_OFF
