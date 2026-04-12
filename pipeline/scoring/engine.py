"""ScoringEngine: assembles StockData from the DB and runs all 4 scorers.

This is the entry point the pipeline runner calls. It:
1. Loads prices + fundamentals for each ticker from SQLite (no API calls)
2. Computes technical indicators (DMA, RSI, momentum) via pandas-ta
3. Runs all 4 bucket scorers
4. Returns a flat list of ScoreOutput (one per ticker per bucket)

The caller (pipeline runner) then applies guardrails and persists to DB.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
from loguru import logger
from sqlalchemy import select

from pipeline.db.base import get_session
from pipeline.db.enums import Country
from pipeline.db.models import Fundamental, Price, Stock
from pipeline.scoring.base import ScoreOutput, StockData
from pipeline.scoring.buckets import (
    DividendGrowthScorer,
    MomentumScorer,
    QualityMomentumScorer,
    QualityValueScorer,
)

PRICE_HISTORY_DAYS = 365 + 30  # ~13 months for 12m-1m momentum
FUNDAMENTAL_QUARTERS = 24      # 6 years


class ScoringEngine:
    """Runs all 4 scorers for every qualifying ticker."""

    def __init__(self, weights: dict[str, dict] | None = None) -> None:
        self._scorers = [
            QualityValueScorer(),
            MomentumScorer(),
            QualityMomentumScorer(),
            DividendGrowthScorer(),
        ]
        self._weights = weights or {}  # bucket → {factor: weight}

    def run(
        self,
        tickers: list[tuple[str, Country]],
        as_of: date | None = None,
    ) -> list[ScoreOutput]:
        """Score all tickers across all 4 buckets. Returns all ScoreOutputs."""
        as_of = as_of or date.today()
        sector_medians = self._compute_sector_medians(tickers)

        results: list[ScoreOutput] = []
        for ticker, country in tickers:
            try:
                stock_data = self._assemble(ticker, country, as_of, sector_medians)
                for scorer in self._scorers:
                    bucket_weights = self._weights.get(scorer.bucket, None)
                    out = scorer.score(stock_data, weights=bucket_weights)
                    results.append(out)
            except Exception as exc:
                logger.warning(f"Scoring failed for {ticker}: {exc}")
        return results

    # ------------------------------------------------------------------
    # StockData assembler
    # ------------------------------------------------------------------

    def _assemble(
        self,
        ticker: str,
        country: Country,
        as_of: date,
        sector_medians: dict[str, float],
    ) -> StockData:
        price_df = self._load_prices(ticker, country, as_of)
        fundamentals = self._load_fundamentals(ticker, country)
        sector = self._load_sector(ticker, country)

        latest_close = float(price_df["close"].iloc[-1]) if not price_df.empty else None
        dma_50 = _rolling_mean(price_df["close"], 50)
        dma_200 = _rolling_mean(price_df["close"], 200)
        rsi_14 = _compute_rsi(price_df["close"], 14)
        high_52w = float(price_df["high"].rolling(252).max().iloc[-1]) if len(price_df) >= 5 else None
        momentum_12m_1m = _compute_momentum(price_df["close"])

        return StockData(
            ticker=ticker,
            country=country,
            sector=sector,
            prices=price_df,
            fundamentals=fundamentals,
            dma_50=dma_50,
            dma_200=dma_200,
            rsi_14=rsi_14,
            high_52w=high_52w,
            momentum_12m_1m=momentum_12m_1m,
            days_to_next_earnings=None,  # set by guardrails layer
            sector_median_pe=sector_medians.get(sector) if sector else None,
            latest_close=latest_close,
        )

    def _load_prices(self, ticker: str, country: Country, as_of: date) -> pd.DataFrame:
        cutoff = as_of - timedelta(days=PRICE_HISTORY_DAYS)
        with get_session() as session:
            stock = session.execute(
                select(Stock).where(Stock.ticker == ticker, Stock.country == country)
            ).scalar_one_or_none()
            if stock is None:
                return pd.DataFrame()
            rows = session.execute(
                select(Price)
                .where(
                    Price.stock_id == stock.id,
                    Price.date >= cutoff,
                    Price.date <= as_of,
                )
                .order_by(Price.date)
            ).scalars().all()

        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(
            [
                {
                    "date": r.date,
                    "open": r.open,
                    "high": r.high,
                    "low": r.low,
                    "close": r.close,
                    "adj_close": r.adj_close,
                    "volume": r.volume,
                }
                for r in rows
            ]
        )

    def _load_fundamentals(self, ticker: str, country: Country) -> list[dict]:
        with get_session() as session:
            stock = session.execute(
                select(Stock).where(Stock.ticker == ticker, Stock.country == country)
            ).scalar_one_or_none()
            if stock is None:
                return []
            rows = session.execute(
                select(Fundamental)
                .where(Fundamental.stock_id == stock.id)
                .order_by(Fundamental.fiscal_date.desc())
                .limit(FUNDAMENTAL_QUARTERS)
            ).scalars().all()

        return [
            {
                "fiscal_date": r.fiscal_date,
                "revenue": r.revenue,
                "net_income": r.net_income,
                "eps": r.eps,
                "total_debt": r.total_debt,
                "total_equity": r.total_equity,
                "debt_equity": r.debt_equity,
                "operating_cash_flow": r.operating_cash_flow,
                "free_cash_flow": r.free_cash_flow,
                "roe": r.roe,
                "gross_margin": r.gross_margin,
                "net_margin": r.net_margin,
                "pe": r.pe,
                "pb": r.pb,
                "dividend_per_share": r.dividend_per_share,
                "dividend_yield": r.dividend_yield,
                "payout_ratio": r.payout_ratio,
                "promoter_holding": r.promoter_holding,
            }
            for r in rows
        ]

    def _load_sector(self, ticker: str, country: Country) -> str | None:
        with get_session() as session:
            stock = session.execute(
                select(Stock.sector).where(Stock.ticker == ticker, Stock.country == country)
            ).scalar_one_or_none()
        return stock  # scalar_one_or_none returns the sector value here

    def _compute_sector_medians(
        self, tickers: list[tuple[str, Country]]
    ) -> dict[str, float]:
        """Compute median P/E per sector for the scoring universe.
        Used by QV and QM scorers for the pe_vs_sector_median factor."""
        sector_pes: dict[str, list[float]] = {}
        with get_session() as session:
            for ticker, country in tickers:
                stock = session.execute(
                    select(Stock).where(Stock.ticker == ticker, Stock.country == country)
                ).scalar_one_or_none()
                if stock is None or not stock.sector:
                    continue
                latest_f = session.execute(
                    select(Fundamental)
                    .where(Fundamental.stock_id == stock.id)
                    .order_by(Fundamental.fiscal_date.desc())
                    .limit(1)
                ).scalar_one_or_none()
                if latest_f and latest_f.pe and latest_f.pe > 0:
                    sector_pes.setdefault(stock.sector, []).append(latest_f.pe)

        return {
            sector: float(np.median(pes))
            for sector, pes in sector_pes.items()
            if pes
        }


# ---------------------------------------------------------------------------
# Technical indicator helpers
# ---------------------------------------------------------------------------


def _rolling_mean(series: pd.Series, window: int) -> float | None:
    if len(series) < window:
        return None
    val = series.rolling(window).mean().iloc[-1]
    return float(val) if not pd.isna(val) else None


def _compute_rsi(series: pd.Series, period: int = 14) -> float | None:
    """Wilder's RSI. Returns the most-recent value."""
    if len(series) < period + 1:
        return None
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    # When avg_loss == 0 (all gains), RSI = 100 by definition
    rs = avg_gain / avg_loss.where(avg_loss != 0, other=float("nan"))
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.where(avg_loss != 0, other=100.0)  # pure uptrend → RSI 100
    val = rsi.iloc[-1]
    return float(val) if not pd.isna(val) else None


def _compute_momentum(series: pd.Series) -> float | None:
    """12m-1m price momentum: return from ~12mo ago to ~1mo ago.
    Academic factor: excludes most-recent month to avoid reversal."""
    if len(series) < 240:  # need ~11 months of data
        return None
    price_1m_ago = series.iloc[-21]   # ~1 month back
    price_12m_ago = series.iloc[-252] if len(series) >= 252 else series.iloc[0]
    if price_12m_ago == 0:
        return None
    return float((price_1m_ago / price_12m_ago) - 1)
