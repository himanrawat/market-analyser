"""Tests for guardrails layer."""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from pipeline.db.enums import Bucket, Country, MacroRegime
from pipeline.scoring.base import ScoreOutput
from pipeline.scoring.guardrails import (
    EARNINGS_BLACKOUT_DAYS,
    HYSTERESIS_BUFFER,
    SECTOR_CAP,
    Guardrails,
    compute_macro_regime,
)

pytestmark = pytest.mark.us


def _score(ticker: str, score: float, qualified: bool = True, bucket: Bucket = Bucket.QUALITY_MOMENTUM) -> ScoreOutput:
    return ScoreOutput(
        ticker=ticker,
        country=Country.US,
        bucket=bucket,
        score=score,
        qualified=qualified,
        factor_scores={},
        disqualifiers=[],
    )


@pytest.fixture()
def guardrails():
    g = Guardrails(picks_per_bucket=3, as_of=date(2026, 4, 7))
    # Patch DB calls to return empty sets
    with (
        patch.object(g, "_load_held_keys", return_value=set()),
        patch.object(g, "_load_upcoming_earnings", return_value=set()),
        patch.object(g, "_load_sectors", return_value={}),
    ):
        yield g


class TestComputeMacroRegime:
    def test_both_above_dma_risk_on(self):
        assert compute_macro_regime(22000, 20000, 5200, 5000) == MacroRegime.RISK_ON

    def test_both_below_dma_risk_off(self):
        assert compute_macro_regime(18000, 20000, 4800, 5000) == MacroRegime.RISK_OFF

    def test_one_below_caution(self):
        assert compute_macro_regime(22000, 20000, 4800, 5000) == MacroRegime.CAUTION

    def test_none_values_treated_as_not_ok(self):
        # Unknown index → treated as not above DMA
        assert compute_macro_regime(None, None, 5200, 5000) == MacroRegime.CAUTION


class TestGuardrails:
    def _apply(self, g: Guardrails, scores, held=None, earnings=None, sectors=None):
        """Helper to apply guardrails with controlled DB state."""
        sector_map = sectors or {}
        with (
            patch.object(g, "_load_held_keys", return_value=held or set()),
            patch.object(g, "_load_upcoming_earnings", return_value=earnings or set()),
            patch.object(g, "_load_sectors", return_value=sector_map),
        ):
            return g._apply_one(
                scores,
                Bucket.QUALITY_MOMENTUM,
                Country.US,
                held or set(),
                earnings or set(),
                sector_map,
                MacroRegime.RISK_ON,
                False,
            )

    def test_top_n_assigned_correctly(self, guardrails):
        scores = [_score(f"T{i}", 100.0 - i) for i in range(10)]
        result = self._apply(guardrails, scores)
        assert len(result.ranked) == 3  # picks_per_bucket=3
        assert result.ranked[0].rank == 1
        assert result.ranked[1].rank == 2
        assert result.ranked[2].rank == 3

    def test_extended_list_has_ranks_beyond_n(self, guardrails):
        scores = [_score(f"T{i}", 100.0 - i) for i in range(10)]
        result = self._apply(guardrails, scores)
        assert all(s.rank and s.rank > 3 for s in result.extended)

    def test_unqualified_excluded(self, guardrails):
        scores = [
            _score("GOOD", 90.0, qualified=True),
            _score("BAD", 95.0, qualified=False),  # higher score but not qualified
        ]
        result = self._apply(guardrails, scores)
        tickers = [s.ticker for s in result.ranked]
        assert "GOOD" in tickers
        assert "BAD" not in tickers

    def test_earnings_blackout_removes_ticker(self, guardrails):
        scores = [_score(f"T{i}", 100.0 - i) for i in range(5)]
        result = self._apply(guardrails, scores, earnings={("T0", Country.US)})
        top_tickers = [s.ticker for s in result.ranked]
        assert "T0" not in top_tickers
        assert "T0" in result.removed_by_blackout

    def test_sector_cap_enforced(self, guardrails):
        # 5 stocks all in same sector → only SECTOR_CAP=3 in top N
        sectors = {(f"T{i}", Country.US): "Technology" for i in range(5)}
        scores = [_score(f"T{i}", 100.0 - i) for i in range(5)]
        result = self._apply(guardrails, scores, sectors=sectors)
        tech_in_top = [s for s in result.ranked if sectors.get((s.ticker, s.country)) == "Technology"]
        assert len(tech_in_top) <= SECTOR_CAP

    def test_hysteresis_keeps_held_stock_near_cutoff(self, guardrails):
        """Held stock with score just above (cutoff - HYSTERESIS_BUFFER) stays in."""
        # picks=3 → cutoff ≈ score of 3rd stock
        scores = [
            _score("T0", 90.0),
            _score("T1", 80.0),
            _score("T2", 70.0),   # cutoff ≈ 70
            _score("T3", 62.0),   # 62 = 70-8 → within buffer (buffer=10) → stays if held
        ]
        # T3 is held and score=62, cutoff=70 → drop = 8 pts < HYSTERESIS_BUFFER(10) → keep
        result = self._apply(guardrails, scores, held={("T3", Country.US)})
        all_tickers = {s.ticker for s in result.ranked + result.extended}
        assert "T3" in all_tickers

    def test_hysteresis_drops_held_stock_far_below_cutoff(self, guardrails):
        """Held stock with score > HYSTERESIS_BUFFER below cutoff is dropped."""
        scores = [
            _score("T0", 90.0),
            _score("T1", 80.0),
            _score("T2", 70.0),   # cutoff = 70
            _score("T3", 50.0),   # 50 = 70-20 → 20 > buffer(10) → dropped
        ]
        result = self._apply(guardrails, scores, held={("T3", Country.US)})
        all_tickers = {s.ticker for s in result.ranked + result.extended}
        assert "T3" not in all_tickers

    def test_risk_off_adds_note(self, guardrails):
        result = guardrails._apply_one(
            [_score("T0", 90.0)],
            Bucket.QUALITY_MOMENTUM, Country.US,
            set(), set(), {},
            MacroRegime.RISK_OFF, False,
        )
        assert any("Defensive Regime" in n for n in result.notes)

    def test_shock_regime_adds_note(self, guardrails):
        result = guardrails._apply_one(
            [_score("T0", 90.0)],
            Bucket.QUALITY_MOMENTUM, Country.US,
            set(), set(), {},
            MacroRegime.RISK_ON, True,
        )
        assert any("Shock Regime" in n for n in result.notes)

    def test_risk_on_no_regime_notes(self, guardrails):
        result = guardrails._apply_one(
            [_score("T0", 90.0)],
            Bucket.QUALITY_MOMENTUM, Country.US,
            set(), set(), {},
            MacroRegime.RISK_ON, False,
        )
        assert result.notes == []
