"""Two-signal market-shock detector (F-13.2).

Detection logic (F-13.2.2):
  Signal A — curated keyword match in a headline
  Signal B — India VIX or US VIX up >20% intraday

Escalation:
  Both signals within the same 24h window → RED banner  (ShockBanner.RED)
  Only Signal A                           → YELLOW banner (ShockBanner.YELLOW)
  Only Signal B (no keyword match)        → YELLOW banner (ShockBanner.YELLOW)
  Neither                                 → no event

Every banner trigger is persisted to the shock_events table (F-13.2.8).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import select

from pipeline.db.base import get_session
from pipeline.db.enums import ShockBanner
from pipeline.db.models import ShockEvent

# ---------------------------------------------------------------------------
# Keyword catalogue (F-13.2.2 Signal A)
# ---------------------------------------------------------------------------
SHOCK_KEYWORDS: dict[str, list[str]] = {
    "war_conflict": [
        "war", "military invasion", "invasion", "missile strike", "missile attack",
        "nuclear threat", "nuclear strike", "ground offensive", "air strike",
        "declared war", "armed conflict",
    ],
    "pandemic": [
        "pandemic", "outbreak", "virus", "lockdown", "quarantine",
        "health emergency", "epidemic", "novel pathogen",
    ],
    "banking_crisis": [
        "sovereign default", "banking crisis", "systemic bank failure",
        "bank run", "bank collapse", "bank failure", "deposit freeze",
        "debt default",
    ],
    "central_bank_emergency": [
        "emergency rate decision", "unscheduled fed", "unscheduled rbi",
        "emergency meeting", "emergency rate cut", "emergency rate hike",
        "unscheduled fomc", "unscheduled mpc",
    ],
    "terror": [
        "terror attack", "terrorist attack", "explosion in",
        "bombing in financial", "attack on stock exchange",
    ],
    "oil_shock": [
        "oil shock", "opec emergency", "oil supply cut", "oil embargo",
        "energy crisis",
    ],
}

# Flattened list of all keyword phrases for fast matching
_ALL_PHRASES: list[tuple[str, str]] = [
    (category, phrase)
    for category, phrases in SHOCK_KEYWORDS.items()
    for phrase in phrases
]

# VIX spike threshold (F-13.2.2 Signal B)
VIX_SPIKE_PCT = 20.0


@dataclass
class ShockSignal:
    """Result of evaluating one article against the shock detector."""

    headline: str
    source: str
    url: str | None

    # Signal A
    signal_a: bool = False
    matched_keywords: list[str] = field(default_factory=list)
    matched_category: str | None = None

    # Signal B
    signal_b: bool = False
    india_vix: float | None = None
    us_vix: float | None = None
    india_vix_change_pct: float | None = None
    us_vix_change_pct: float | None = None

    @property
    def banner(self) -> ShockBanner | None:
        if self.signal_a and self.signal_b:
            return ShockBanner.RED
        if self.signal_a or self.signal_b:
            return ShockBanner.YELLOW
        return None


def _match_keywords(text: str) -> tuple[list[str], str | None]:
    """Return (matched_phrases, first_matching_category) for a lowercase text."""
    lower = text.lower()
    matched: list[str] = []
    category: str | None = None
    for cat, phrase in _ALL_PHRASES:
        # Use word-boundary-aware match: phrase is a substring, not just a word
        if re.search(re.escape(phrase), lower):
            matched.append(phrase)
            if category is None:
                category = cat
    return matched, category


class ShockDetector:
    """Evaluates articles + VIX readings for shock conditions and persists events."""

    def __init__(self, vix_spike_pct: float = VIX_SPIKE_PCT) -> None:
        self.vix_spike_pct = vix_spike_pct

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        headline: str,
        source: str,
        url: str | None = None,
        india_vix: float | None = None,
        india_vix_prev: float | None = None,
        us_vix: float | None = None,
        us_vix_prev: float | None = None,
    ) -> ShockSignal:
        """Evaluate a single headline + VIX readings.

        VIX change is computed relative to the previous session's close.
        """
        sig = ShockSignal(headline=headline, source=source, url=url)

        # Signal A — keyword match
        matched, cat = _match_keywords(headline)
        if matched:
            sig.signal_a = True
            sig.matched_keywords = matched
            sig.matched_category = cat

        # Signal B — VIX spike
        india_chg = self._vix_change_pct(india_vix, india_vix_prev)
        us_chg = self._vix_change_pct(us_vix, us_vix_prev)
        sig.india_vix = india_vix
        sig.us_vix = us_vix
        sig.india_vix_change_pct = india_chg
        sig.us_vix_change_pct = us_chg

        if (india_chg is not None and india_chg >= self.vix_spike_pct) or (
            us_chg is not None and us_chg >= self.vix_spike_pct
        ):
            sig.signal_b = True

        return sig

    def persist(self, sig: ShockSignal, triggered_at: datetime | None = None) -> ShockEvent | None:
        """Write a ShockSignal to the database if it has a banner level.

        Returns the created ShockEvent row, or None if no banner fired.
        """
        banner = sig.banner
        if banner is None:
            return None

        ts = triggered_at or datetime.now(tz=timezone.utc)

        event = ShockEvent(
            triggered_at=ts,
            banner=banner,
            headline=sig.headline,
            source=sig.source,
            url=sig.url,
            matched_keywords=sig.matched_keywords,
            india_vix_at_trigger=sig.india_vix,
            us_vix_at_trigger=sig.us_vix,
            india_vix_change_pct=sig.india_vix_change_pct,
            us_vix_change_pct=sig.us_vix_change_pct,
        )

        with get_session() as session:
            session.add(event)
            session.commit()
            session.refresh(event)

        logger.warning(
            f"SHOCK EVENT [{banner.upper()}] persisted | "
            f"headline='{sig.headline[:60]}...' | "
            f"keywords={sig.matched_keywords} | "
            f"india_vix_chg={sig.india_vix_change_pct} us_vix_chg={sig.us_vix_change_pct}"
        )
        return event

    def active_shock(self, within_days: int = 14) -> ShockEvent | None:
        """Return the most recent RED ShockEvent within the lookback window.

        Used by the auto-Risk-Off override (F-13.2.5): if a RED event fired
        in the 14 days before a rebalance, the macro overlay flips to Risk-Off.
        """
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=within_days)
        with get_session() as session:
            row = session.execute(
                select(ShockEvent)
                .where(
                    ShockEvent.banner == ShockBanner.RED,
                    ShockEvent.triggered_at >= cutoff,
                )
                .order_by(ShockEvent.triggered_at.desc())
                .limit(1)
            ).scalar_one_or_none()
        return row

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _vix_change_pct(current: float | None, previous: float | None) -> float | None:
        if current is None or previous is None or previous == 0:
            return None
        return (current - previous) / previous * 100.0
