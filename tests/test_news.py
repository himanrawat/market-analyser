"""Tests for VADER sentiment scorer and two-signal shock detector."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from pipeline.db.enums import SentimentLabel, ShockBanner
from pipeline.news.sentiment import SentimentResult, SentimentScorer
from pipeline.news.shock import ShockDetector, ShockSignal, _match_keywords


class TestSentimentScorer:
    @pytest.fixture()
    def scorer(self):
        return SentimentScorer()

    def test_positive_headline(self, scorer):
        result = scorer.score("Company reports record profits, stock soars to all-time high")
        assert result.label == SentimentLabel.POSITIVE
        assert result.compound >= 0.05

    def test_negative_headline(self, scorer):
        result = scorer.score("Company collapses, massive losses, investors panic")
        assert result.label == SentimentLabel.NEGATIVE
        assert result.compound <= -0.05

    def test_neutral_headline(self, scorer):
        result = scorer.score("Company announces quarterly earnings release date")
        assert result.label == SentimentLabel.NEUTRAL

    def test_compound_in_range(self, scorer):
        result = scorer.score("Stock market opens higher")
        assert -1.0 <= result.compound <= 1.0

    def test_score_many_returns_correct_count(self, scorer):
        headlines = [
            "Great earnings beat",
            "Company files for bankruptcy",
            "Quarterly results announced",
        ]
        results = scorer.score_many(headlines)
        assert len(results) == 3
        assert all(isinstance(r, SentimentResult) for r in results)

    def test_score_many_order_preserved(self, scorer):
        texts = ["This is good", "This is bad"]
        results = scorer.score_many(texts)
        assert results[0].compound > results[1].compound

    def test_empty_string_is_neutral(self, scorer):
        result = scorer.score("")
        assert result.label == SentimentLabel.NEUTRAL

    def test_factor_scores_sum_approx_to_one(self, scorer):
        result = scorer.score("Markets react to interest rate decision")
        total = result.positive + result.neutral + result.negative
        assert abs(total - 1.0) < 0.01


class TestKeywordMatching:
    def test_war_keyword_matched(self):
        matched, cat = _match_keywords("Russia launches military invasion of Ukraine")
        assert len(matched) > 0
        assert cat == "war_conflict"

    def test_pandemic_keyword_matched(self):
        matched, cat = _match_keywords("WHO declares pandemic after new virus outbreak")
        assert "pandemic" in matched or "virus" in matched or "outbreak" in matched
        assert cat == "pandemic"

    def test_banking_crisis_matched(self):
        matched, cat = _match_keywords("Major bank faces systemic bank failure risk")
        assert len(matched) > 0
        assert cat == "banking_crisis"

    def test_no_match_returns_empty(self):
        matched, cat = _match_keywords("Apple releases new iPhone model with improved camera")
        assert matched == []
        assert cat is None

    def test_case_insensitive_matching(self):
        matched, _ = _match_keywords("PANDEMIC declared by WHO")
        assert len(matched) > 0

    def test_multiple_keywords_matched(self):
        matched, _ = _match_keywords("War and pandemic declared simultaneously")
        assert len(matched) >= 2

    def test_oil_shock_keyword(self):
        # "oil shock" phrase alone — avoids accidental central_bank_emergency match
        matched, cat = _match_keywords("crude oil shock disrupts global supply chains")
        assert len(matched) > 0
        assert cat == "oil_shock"


class TestShockDetector:
    @pytest.fixture()
    def detector(self):
        return ShockDetector(vix_spike_pct=20.0)

    def test_both_signals_is_red(self, detector):
        sig = detector.evaluate(
            headline="Military invasion of sovereign nation declared",
            source="Reuters",
            india_vix=22.0,
            india_vix_prev=18.0,  # +22.2% > 20%
        )
        assert sig.signal_a is True
        assert sig.signal_b is True
        assert sig.banner == ShockBanner.RED

    def test_keyword_only_is_yellow(self, detector):
        sig = detector.evaluate(
            headline="New pandemic outbreak detected in Southeast Asia",
            source="Bloomberg",
            india_vix=15.0,
            india_vix_prev=14.5,  # only +3.4% < 20%
        )
        assert sig.signal_a is True
        assert sig.signal_b is False
        assert sig.banner == ShockBanner.YELLOW

    def test_vix_only_is_yellow(self, detector):
        sig = detector.evaluate(
            headline="Markets open lower ahead of earnings season",
            source="FT",
            us_vix=30.0,
            us_vix_prev=20.0,  # +50% > 20%
        )
        assert sig.signal_a is False
        assert sig.signal_b is True
        assert sig.banner == ShockBanner.YELLOW

    def test_no_signals_is_none(self, detector):
        sig = detector.evaluate(
            headline="Tech company announces new product line",
            source="TechCrunch",
            us_vix=18.0,
            us_vix_prev=17.5,  # +2.9%
        )
        assert sig.banner is None

    def test_exactly_at_threshold_fires_signal_b(self, detector):
        # exactly 20% → should fire
        sig = detector.evaluate(
            headline="Routine market update",
            source="Reuters",
            us_vix=24.0,
            us_vix_prev=20.0,  # exactly +20%
        )
        assert sig.signal_b is True

    def test_just_below_threshold_does_not_fire(self, detector):
        sig = detector.evaluate(
            headline="Routine market update",
            source="Reuters",
            us_vix=23.9,
            us_vix_prev=20.0,  # +19.5%
        )
        assert sig.signal_b is False

    def test_no_vix_data_no_signal_b(self, detector):
        sig = detector.evaluate(
            headline="Banking crisis escalates",
            source="FT",
        )
        assert sig.signal_b is False
        # Signal A still fires
        assert sig.signal_a is True

    def test_vix_change_pct_computed_correctly(self, detector):
        sig = detector.evaluate(
            headline="test",
            source="test",
            india_vix=25.0,
            india_vix_prev=20.0,
        )
        assert abs(sig.india_vix_change_pct - 25.0) < 0.01

    def test_persist_skips_when_no_banner(self, detector):
        sig = ShockSignal(headline="boring headline", source="test", url=None)
        result = detector.persist(sig)
        assert result is None

    def test_persist_writes_to_db(self, detector):
        sig = ShockSignal(
            headline="War declared, markets panic",
            source="Reuters",
            url=None,
            signal_a=True,
            matched_keywords=["war"],
            signal_b=True,
            india_vix=25.0,
            us_vix=30.0,
            india_vix_change_pct=25.0,
            us_vix_change_pct=30.0,
        )
        assert sig.banner == ShockBanner.RED

        mock_session = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_session)
        mock_cm.__exit__ = MagicMock(return_value=False)

        with patch("pipeline.news.shock.get_session", return_value=mock_cm):
            detector.persist(sig, triggered_at=datetime(2026, 4, 7, tzinfo=timezone.utc))

        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

    def test_active_shock_queries_db(self, detector):
        mock_session = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_session)
        mock_cm.__exit__ = MagicMock(return_value=False)

        mock_session.execute.return_value.scalar_one_or_none.return_value = None

        with patch("pipeline.news.shock.get_session", return_value=mock_cm):
            result = detector.active_shock(within_days=14)

        assert result is None
        mock_session.execute.assert_called_once()

    def test_india_vix_triggers_signal_b(self, detector):
        # India VIX alone (US VIX normal) should fire Signal B
        sig = detector.evaluate(
            headline="Routine update",
            source="test",
            india_vix=27.0,
            india_vix_prev=20.0,  # +35%
            us_vix=18.0,
            us_vix_prev=17.8,    # +1.1%
        )
        assert sig.signal_b is True

    def test_us_vix_triggers_signal_b(self, detector):
        # US VIX alone (India VIX normal) should fire Signal B
        sig = detector.evaluate(
            headline="Routine update",
            source="test",
            india_vix=15.0,
            india_vix_prev=14.8,  # +1.4%
            us_vix=36.0,
            us_vix_prev=20.0,    # +80%
        )
        assert sig.signal_b is True
