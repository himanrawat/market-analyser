"""Tests for the four bucket scorers.

All tests construct StockData directly — no DB, no network.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from pipeline.db.enums import Bucket, Country
from pipeline.scoring.base import (
    ScoreOutput,
    StockData,
    compute_cagr,
    scale,
    score_above_dma,
    score_debt_equity,
    score_distance_from_high,
    score_dma_crossover,
    score_rsi,
    score_roe,
)
from pipeline.scoring.buckets import (
    DividendGrowthScorer,
    MomentumScorer,
    QualityMomentumScorer,
    QualityValueScorer,
)
from pipeline.scoring.engine import _compute_rsi, _compute_momentum, _rolling_mean


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _prices(n: int = 300, start_price: float = 100.0, trend: float = 0.001) -> pd.DataFrame:
    """Generate a simple upward-trending price series."""
    closes = [start_price * (1 + trend) ** i for i in range(n)]
    return pd.DataFrame(
        {
            "date": [date(2024, 1, 1) + timedelta(days=i) for i in range(n)],
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "adj_close": closes,
            "volume": [1_000_000] * n,
        }
    )


def _fundamentals(
    n_quarters: int = 20,
    roe: float = 22.0,
    de: float = 0.3,
    eps: float = 10.0,
    pe: float = 18.0,
    fcf: float = 500.0,
    div_yield: float = 1.5,
    div_per_share: float = 5.0,
    payout_ratio: float = 0.35,
    net_margin: float = 0.15,
) -> list[dict]:
    return [
        {
            "fiscal_date": date(2024, 1, 1) - timedelta(days=90 * i),
            "revenue": 10_000 + i * 100,
            "net_income": 1_500 + i * 10,
            "eps": eps * (1.03 ** -i),
            "total_debt": 1_000,
            "total_equity": 5_000,
            "debt_equity": de,
            "operating_cash_flow": 600,
            "free_cash_flow": fcf,
            "roe": roe,
            "gross_margin": 0.30,
            "net_margin": net_margin,
            "pe": pe,
            "pb": 3.0,
            "dividend_per_share": div_per_share * (0.95 ** i),
            "dividend_yield": div_yield,
            "payout_ratio": payout_ratio,
            "promoter_holding": 55.0,
        }
        for i in range(n_quarters)
    ]


def _stock_data(
    ticker: str = "AAPL",
    country: Country = Country.US,
    sector: str = "Technology",
    n_prices: int = 300,
    sector_median_pe: float = 22.0,
    **kw,
) -> StockData:
    prices = _prices(n_prices)
    f = _fundamentals(**kw)
    latest = float(prices["close"].iloc[-1])
    return StockData(
        ticker=ticker,
        country=country,
        sector=sector,
        prices=prices,
        fundamentals=f,
        dma_50=latest * 0.97,      # price above 50 DMA
        dma_200=latest * 0.85,     # price above 200 DMA
        rsi_14=62.0,               # healthy range
        high_52w=latest * 1.05,    # within 5% of 52wk high
        low_52w=latest * 0.70,     # 52wk low
        momentum_12m_1m=0.20,      # 20% momentum
        days_to_next_earnings=30,
        sector_median_pe=sector_median_pe,
        latest_close=latest,
    )


# ---------------------------------------------------------------------------
# Primitive tests
# ---------------------------------------------------------------------------


class TestPrimitives:
    def test_scale_clamps_low(self):
        assert scale(-10, 0, 100) == 0.0

    def test_scale_clamps_high(self):
        assert scale(200, 0, 100) == 1.0

    def test_scale_midpoint(self):
        assert abs(scale(50, 0, 100) - 0.5) < 1e-9

    def test_score_roe_full(self):
        assert score_roe(25.0, 15) == 15.0

    def test_score_roe_zero(self):
        assert score_roe(4.0, 15) == 0.0

    def test_score_roe_partial(self):
        val = score_roe(14.0, 15)
        assert 0 < val < 15

    def test_score_roe_none(self):
        assert score_roe(None, 15) == 0.0

    def test_score_debt_equity_low(self):
        assert score_debt_equity(0.2, 10) == 10.0

    def test_score_debt_equity_high(self):
        assert score_debt_equity(3.0, 10) == 0.0

    def test_score_above_dma_true(self):
        assert score_above_dma(120.0, 100.0, 10) == 10.0

    def test_score_above_dma_false(self):
        assert score_above_dma(80.0, 100.0, 10) == 0.0

    def test_score_dma_crossover_true(self):
        assert score_dma_crossover(110.0, 100.0, 10) == 10.0

    def test_score_dma_crossover_false(self):
        assert score_dma_crossover(90.0, 100.0, 10) == 0.0

    def test_score_distance_within(self):
        assert score_distance_from_high(95.0, 100.0, 10, within_pct=10.0) == 10.0

    def test_score_distance_outside(self):
        assert score_distance_from_high(80.0, 100.0, 10, within_pct=10.0) == 0.0

    def test_score_rsi_healthy(self):
        assert score_rsi(65.0, 10) == 10.0

    def test_score_rsi_overbought(self):
        assert score_rsi(90.0, 10) < 0

    def test_score_rsi_weak(self):
        assert score_rsi(40.0, 10) == 0.0

    def test_compute_cagr_basic(self):
        # 16 quarters starting at 100, ending at ~200 (4-year ~19% CAGR)
        values = [100 * (1.19 ** (i / 4)) for i in range(16, -1, -1)]
        cagr = compute_cagr(values)
        assert cagr is not None
        assert abs(cagr - 0.19) < 0.02

    def test_compute_cagr_too_few(self):
        assert compute_cagr([100.0, 110.0]) is None


# ---------------------------------------------------------------------------
# Technical indicator helpers
# ---------------------------------------------------------------------------


class TestTechnicalIndicators:
    def test_rolling_mean_insufficient_data(self):
        s = pd.Series([1.0, 2.0, 3.0])
        assert _rolling_mean(s, 50) is None

    def test_rolling_mean_correct(self):
        s = pd.Series([float(i) for i in range(1, 201)])
        val = _rolling_mean(s, 50)
        assert val is not None
        assert abs(val - 175.5) < 1e-6  # mean of 151..200

    def test_rsi_range(self):
        # Monotonically rising prices → RSI should be high
        s = pd.Series([float(100 + i) for i in range(50)])
        rsi = _compute_rsi(s)
        assert rsi is not None
        assert rsi > 80

    def test_rsi_falling(self):
        s = pd.Series([float(200 - i) for i in range(50)])
        rsi = _compute_rsi(s)
        assert rsi is not None
        assert rsi < 20

    def test_momentum_positive(self):
        # Steady uptrend → positive momentum
        s = pd.Series([100.0 * (1.001 ** i) for i in range(300)])
        mom = _compute_momentum(s)
        assert mom is not None
        assert mom > 0

    def test_momentum_insufficient_data(self):
        s = pd.Series([100.0] * 100)
        assert _compute_momentum(s) is None


# ---------------------------------------------------------------------------
# Quality + Value scorer
# ---------------------------------------------------------------------------


class TestQualityValueScorer:
    def test_high_quality_stock_scores_high(self):
        data = _stock_data(sector_median_pe=25.0)
        result = QualityValueScorer().score(data)
        assert isinstance(result, ScoreOutput)
        assert result.score > 40  # with good fundamentals should score well
        assert result.bucket == Bucket.QUALITY_VALUE

    def test_high_debt_is_disqualified(self):
        data = _stock_data(de=3.0)
        result = QualityValueScorer().score(data)
        assert not result.qualified
        assert any("high_debt" in d for d in result.disqualifiers)

    def test_factor_breakdown_present(self):
        data = _stock_data()
        result = QualityValueScorer().score(data)
        assert "roe_5yr_avg" in result.factor_scores
        assert "debt_equity" in result.factor_scores
        assert "pe_vs_sector_median" in result.factor_scores

    def test_score_bounded_0_100(self):
        data = _stock_data()
        result = QualityValueScorer().score(data)
        assert 0 <= result.score <= 100

    def test_no_fundamentals_scores_low(self):
        data = _stock_data()
        data.fundamentals = []
        result = QualityValueScorer().score(data)
        assert result.score < 20

    def test_financial_sector_skips_de(self):
        """Banks shouldn't be disqualified on D/E."""
        data = _stock_data(sector="Financials", de=5.0)
        result = QualityValueScorer().score(data)
        # Financial sector → de check skipped → no "high_debt" DQ
        assert not any("high_debt" in d for d in result.disqualifiers)


# ---------------------------------------------------------------------------
# Momentum scorer
# ---------------------------------------------------------------------------


class TestMomentumScorer:
    def test_uptrending_stock_qualifies(self):
        data = _stock_data()
        result = MomentumScorer().score(data)
        assert result.qualified
        assert result.score > 30

    def test_below_200dma_disqualified(self):
        data = _stock_data()
        data.dma_200 = data.latest_close * 1.2  # price below 200 DMA
        result = MomentumScorer().score(data)
        assert not result.qualified
        assert "below_200dma" in result.disqualifiers

    def test_broken_trend_disqualified(self):
        data = _stock_data()
        data.dma_50 = data.dma_200 * 0.9  # 50 DMA below 200 DMA
        result = MomentumScorer().score(data)
        assert not result.qualified
        assert any("broken_trend" in d for d in result.disqualifiers)

    def test_factor_breakdown_present(self):
        data = _stock_data()
        result = MomentumScorer().score(data)
        for factor in ["momentum_12m_1m", "above_200dma", "rsi_14"]:
            assert factor in result.factor_scores


# ---------------------------------------------------------------------------
# Quality + Momentum scorer
# ---------------------------------------------------------------------------


class TestQualityMomentumScorer:
    def test_ideal_stock_qualifies(self):
        data = _stock_data()
        result = QualityMomentumScorer().score(data)
        assert result.qualified
        assert result.score > 50

    def test_low_roe_fundamental_failure(self):
        data = _stock_data(roe=3.0)
        result = QualityMomentumScorer().score(data)
        assert not result.qualified
        assert "fundamental_quality_failure" in result.disqualifiers

    def test_trend_failure_disqualifies(self):
        data = _stock_data()
        data.dma_200 = data.latest_close * 1.5  # below 200 DMA
        result = QualityMomentumScorer().score(data)
        assert not result.qualified
        assert "price_trend_failure" in result.disqualifiers

    def test_both_failures_both_in_dq(self):
        data = _stock_data(roe=2.0)
        data.dma_200 = data.latest_close * 1.5
        result = QualityMomentumScorer().score(data)
        assert "fundamental_quality_failure" in result.disqualifiers
        assert "price_trend_failure" in result.disqualifiers


# ---------------------------------------------------------------------------
# Dividend Growth scorer
# ---------------------------------------------------------------------------


class TestDividendGrowthScorer:
    def test_good_dividend_stock_scores_well(self):
        data = _stock_data(div_yield=2.5, div_per_share=8.0, payout_ratio=0.40, fcf=1000.0)
        result = DividendGrowthScorer().score(data)
        assert isinstance(result, ScoreOutput)
        assert result.score > 20

    def test_high_payout_disqualified(self):
        data = _stock_data(payout_ratio=0.90)
        result = DividendGrowthScorer().score(data)
        assert not result.qualified
        assert "payout_ratio_too_high" in result.disqualifiers

    def test_negative_fcf_disqualified(self):
        data = _stock_data(fcf=-100.0)
        result = DividendGrowthScorer().score(data)
        assert not result.qualified
        assert "negative_fcf" in result.disqualifiers

    def test_factor_breakdown_present(self):
        data = _stock_data()
        result = DividendGrowthScorer().score(data)
        for factor in ["consecutive_dividend_years", "dividend_yield", "payout_ratio"]:
            assert factor in result.factor_scores

    def test_india_shorter_consecutive_threshold(self):
        """India requires 5+ years vs US 10+. Same underlying data should score higher for India."""
        data_india = _stock_data(country=Country.INDIA, div_per_share=5.0)
        data_us = _stock_data(country=Country.US, div_per_share=5.0)
        result_india = DividendGrowthScorer().score(data_india)
        result_us = DividendGrowthScorer().score(data_us)
        # India score should be >= US score for same dividend history (lower bar)
        assert result_india.score >= result_us.score
