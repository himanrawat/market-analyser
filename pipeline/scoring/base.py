"""Base types and helpers shared by all bucket scorers.

A scorer takes StockData (pre-fetched, in-memory) and returns a ScoreOutput.
StockData is assembled by the pipeline runner from DB-resident prices,
fundamentals, and events — scorers themselves never touch the DB or network.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Input value object — everything a scorer could need, pre-computed
# ---------------------------------------------------------------------------


@dataclass
class StockData:
    """All the data a scorer needs for one stock. Built by the data assembler."""

    ticker: str
    country: str          # "IN" or "US"
    sector: str | None

    # --- Prices ---
    prices: pd.DataFrame  # columns: date, close, adj_close, volume, high, low, open
    # (sorted ascending by date, index reset)

    # --- Fundamentals (list of dicts, most-recent first) ---
    fundamentals: list[dict]  # keys match FundamentalSnapshot fields

    # --- Derived technical indicators (computed by assembler) ---
    dma_50: float | None
    dma_200: float | None
    rsi_14: float | None
    high_52w: float | None
    low_52w: float | None
    momentum_12m_1m: float | None  # (price_11m_ago / price_1m_ago) - 1

    # --- Events ---
    days_to_next_earnings: int | None  # None = no known upcoming earnings

    # --- Sector context (populated by guardrails layer) ---
    sector_median_pe: float | None = None

    # --- Latest price ---
    latest_close: float | None = None


# ---------------------------------------------------------------------------
# Output value object
# ---------------------------------------------------------------------------


@dataclass
class ScoreOutput:
    ticker: str
    bucket: str                          # Bucket enum value
    score: float                         # 0–100
    qualified: bool                      # passed all disqualifiers
    factor_scores: dict[str, float] = field(default_factory=dict)
    disqualifiers: list[str] = field(default_factory=list)
    rank: int | None = None


# ---------------------------------------------------------------------------
# Scorer protocol
# ---------------------------------------------------------------------------


class BucketScorer(Protocol):
    """Every bucket scorer must implement this interface."""

    bucket: str

    def score(self, data: StockData, weights: dict[str, float] | None = None) -> ScoreOutput:
        ...


# ---------------------------------------------------------------------------
# Shared scoring primitives
# ---------------------------------------------------------------------------


def scale(value: float, low: float, high: float) -> float:
    """Linearly scale `value` from [low, high] → [0, 1]. Clamps at boundaries."""
    if high == low:
        return 1.0 if value >= high else 0.0
    return max(0.0, min(1.0, (value - low) / (high - low)))


def score_roe(roe: float | None, full_pts: float, low_threshold: float = 8.0) -> float:
    """ROE 5yr avg: >20% = full, scales to 0 at <low_threshold (default 8%)."""
    if roe is None:
        return 0.0
    return scale(roe, low_threshold, 20.0) * full_pts


def score_debt_equity(de: float | None, full_pts: float, max_de: float = 2.0) -> float:
    """D/E: <0.5 = full, >max_de = zero. Banks/NBFCs handled at caller (pass None)."""
    if de is None:
        return full_pts * 0.5  # partial credit if unknown
    return scale(-de, -max_de, -0.5) * full_pts


def score_cagr(cagr: float | None, full_pts: float, target: float = 15.0) -> float:
    """CAGR above `target` gets full points. Scales from 0 at 0%."""
    if cagr is None:
        return 0.0
    return scale(cagr, 0.0, target) * full_pts


def score_fcf(fundamentals: list[dict], full_pts: float, years: int = 3) -> float:
    """FCF positive & growing for last `years` years."""
    fcfs = [f.get("free_cash_flow") for f in fundamentals[:years * 4]]  # quarterly
    fcfs = [v for v in fcfs if v is not None]
    if len(fcfs) < 4:
        return 0.0
    # Positive in all available periods
    if any(v <= 0 for v in fcfs):
        return full_pts * 0.3  # positive but not consistently
    # Growing trend (simple: latest > earliest)
    if fcfs[0] > fcfs[-1]:
        return full_pts
    return full_pts * 0.7  # positive but not growing


def score_pe_vs_sector(pe: float | None, sector_median: float | None, full_pts: float) -> float:
    """P/E vs sector median. Below median = full, above = 0."""
    if pe is None or sector_median is None:
        return 0.0
    if pe <= sector_median:
        return full_pts
    return 0.0


def score_pe_vs_own_history(
    current_pe: float | None, historical_pes: list[float], full_pts: float
) -> float:
    """P/E vs stock's own 5-year median. Below median = full."""
    if current_pe is None or not historical_pes:
        return 0.0
    own_median = float(np.median(historical_pes))
    if current_pe <= own_median:
        return full_pts
    return 0.0


def score_above_dma(price: float | None, dma: float | None, full_pts: float) -> float:
    if price is None or dma is None:
        return 0.0
    return full_pts if price > dma else 0.0


def score_dma_crossover(dma_50: float | None, dma_200: float | None, full_pts: float) -> float:
    """50 DMA > 200 DMA (Stage 2 uptrend)."""
    if dma_50 is None or dma_200 is None:
        return 0.0
    return full_pts if dma_50 > dma_200 else 0.0


def score_distance_from_high(
    price: float | None, high_52w: float | None, full_pts: float, within_pct: float = 15.0
) -> float:
    """Within `within_pct`% of 52-week high = full points."""
    if price is None or high_52w is None or high_52w == 0:
        return 0.0
    distance_pct = (high_52w - price) / high_52w * 100
    if distance_pct <= within_pct:
        return full_pts
    return 0.0


def score_rsi(rsi: float | None, full_pts: float) -> float:
    """RSI 50–80 = full. >85 = penalty (return negative). <50 = 0."""
    if rsi is None:
        return 0.0
    if rsi > 85:
        return -full_pts * 0.5
    if 50 <= rsi <= 80:
        return full_pts
    return 0.0


def score_volume_trend(prices: pd.DataFrame, full_pts: float) -> float:
    """Up-volume > down-volume over last 20 sessions."""
    if prices.empty or len(prices) < 10:
        return 0.0
    recent = prices.tail(20).copy()
    recent["up"] = recent["close"] > recent["close"].shift(1)
    up_vol = recent.loc[recent["up"], "volume"].sum()
    down_vol = recent.loc[~recent["up"], "volume"].sum()
    total = up_vol + down_vol
    if total == 0:
        return 0.0
    return (up_vol / total) * full_pts


def score_earnings_beat(fundamentals: list[dict], full_pts: float) -> float:
    """Last quarter actual EPS > estimate by >5%."""
    if not fundamentals:
        return 0.0
    latest = fundamentals[0]
    eps = latest.get("eps")
    eps_est = latest.get("eps_estimate")
    if eps is None or eps_est is None or eps_est == 0:
        return 0.0
    beat_pct = (eps - eps_est) / abs(eps_est) * 100
    if beat_pct > 5:
        return full_pts
    return 0.0


def score_sales_growth(fundamentals: list[dict], full_pts: float, target_pct: float = 15.0) -> float:
    """Revenue YoY growth (latest quarter vs same quarter 1yr ago)."""
    if len(fundamentals) < 5:
        return 0.0
    latest_rev = fundamentals[0].get("revenue")
    year_ago_rev = fundamentals[4].get("revenue")  # 4 quarters back
    if latest_rev is None or year_ago_rev is None or year_ago_rev == 0:
        return 0.0
    growth_pct = (latest_rev - year_ago_rev) / abs(year_ago_rev) * 100
    return scale(growth_pct, 0.0, target_pct) * full_pts


def compute_cagr(values: list[float], periods_per_year: int = 4) -> float | None:
    """Compute CAGR from a list of quarterly values (most-recent first).
    Returns None if not enough data or impossible to compute."""
    clean = [v for v in values if v is not None and v != 0]
    if len(clean) < 5:
        return None
    n_years = (len(clean) - 1) / periods_per_year
    if n_years <= 0:
        return None
    try:
        return (clean[0] / clean[-1]) ** (1 / n_years) - 1
    except (ZeroDivisionError, ValueError):
        return None
