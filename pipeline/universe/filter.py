"""UniverseFilter: applies hard filters (F-2.1 through F-2.5) before scoring.

Reduces ~1000 stocks → ~300-400 qualifying stocks. Filters are:
  F-2.1  Market cap < ₹5,000 cr (India) or < $2B (US)
  F-2.2  Avg daily volume < ₹10 cr/day (India) or < $10M/day (US)
  F-2.3  Listed less than 3 years ago
  F-2.4  Currently suspended or in F&O ban (India)
  F-2.5  (implicit) Not in universe = already excluded by loader

The filter reads prices from the DB to compute avg volume — it does NOT
make new API calls for the bulk filter pass. Profile data (market_cap,
listing_date, is_suspended) must already be present from the loader step.

Returns a list of (ticker, country) pairs that passed all filters.
Stocks that fail are logged with their specific disqualification reason.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd
from loguru import logger
from sqlalchemy import select

from pipeline.db.base import get_session
from pipeline.db.enums import Country
from pipeline.db.models import Price, Stock

# Thresholds from PRD F-2.1 and F-2.2
MIN_MARKET_CAP_INR = 5_000 * 1e7        # ₹5,000 crore = ₹5,000 × 1e7 (absolute INR)
MIN_MARKET_CAP_USD = 2_000_000_000       # $2B
MIN_AVG_VOLUME_INR = 10 * 1e7           # ₹10 crore/day in value traded
MIN_AVG_VOLUME_USD = 10_000_000          # $10M/day in value traded
MIN_LISTING_YEARS = 3
VOLUME_LOOKBACK_DAYS = 90               # 3-month window for avg volume


@dataclass
class FilterResult:
    passed: list[tuple[str, Country]] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)   # ticker → reason

    @property
    def pass_count(self) -> int:
        return len(self.passed)

    @property
    def fail_count(self) -> int:
        return len(self.failed)


class UniverseFilter:
    """Applies all hard filters and returns a FilterResult."""

    def __init__(self, as_of: date | None = None) -> None:
        self.as_of = as_of or date.today()

    def run(self, tickers: list[tuple[str, Country]]) -> FilterResult:
        """Filter a list of (ticker, country) pairs. Returns FilterResult."""
        result = FilterResult()
        stocks = self._load_stocks(tickers)
        prices_by_stock = self._load_recent_prices(list(stocks.keys()))

        for (ticker, country), stock in stocks.items():
            reason = self._check(stock, prices_by_stock.get(stock.id, []))
            if reason:
                logger.debug(f"[filter] FAIL {ticker}: {reason}")
                result.failed[ticker] = reason
            else:
                result.passed.append((ticker, country))

        logger.info(
            f"Universe filter: {result.pass_count} passed, "
            f"{result.fail_count} failed out of {len(tickers)} total"
        )
        return result

    # ------------------------------------------------------------------
    # Per-stock check — returns failure reason string or None if passed
    # ------------------------------------------------------------------

    def _check(self, stock: Stock, recent_prices: list[Price]) -> str | None:
        # F-2.4: suspended or F&O ban
        if stock.is_suspended:
            return "suspended"
        if stock.in_fno_ban:
            return "fno_ban"

        # F-2.3: listed less than 3 years
        if stock.listing_date is not None:
            age_days = (self.as_of - stock.listing_date).days
            if age_days < MIN_LISTING_YEARS * 365:
                return f"listed_too_recently ({age_days}d)"
        # If listing_date is unknown we let it pass — benefit of the doubt

        # F-2.1: market cap
        if stock.market_cap is not None:
            min_cap = (
                MIN_MARKET_CAP_INR
                if stock.country == Country.INDIA
                else MIN_MARKET_CAP_USD
            )
            if stock.market_cap < min_cap:
                return f"market_cap_too_small ({stock.market_cap:.0f})"

        # F-2.2: average daily value traded
        if recent_prices:
            reason = self._check_volume(stock, recent_prices)
            if reason:
                return reason

        return None

    def _check_volume(self, stock: Stock, prices: list[Price]) -> str | None:
        """Compute avg daily value traded (close × volume) over the lookback window."""
        df = pd.DataFrame(
            {"close": [p.close for p in prices], "volume": [p.volume for p in prices]}
        )
        if df.empty:
            return None  # no price data yet — pass through for now
        df["value"] = df["close"] * df["volume"]
        avg_value = df["value"].mean()

        min_value = (
            MIN_AVG_VOLUME_INR
            if stock.country == Country.INDIA
            else MIN_AVG_VOLUME_USD
        )
        if avg_value < min_value:
            return f"low_avg_volume ({avg_value:.0f})"
        return None

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    def _load_stocks(
        self, tickers: list[tuple[str, Country]]
    ) -> dict[tuple[str, Country], Stock]:
        """Bulk-load Stock rows for all tickers in one query."""
        if not tickers:
            return {}
        ticker_strs = [t for t, _ in tickers]
        with get_session() as session:
            rows = session.execute(
                select(Stock).where(Stock.ticker.in_(ticker_strs))
            ).scalars().all()
        return {(s.ticker, s.country): s for s in rows}

    def _load_recent_prices(self, stock_ids: list[int]) -> dict[int, list[Price]]:
        """Bulk-load recent prices for volume computation."""
        if not stock_ids:
            return {}
        cutoff = self.as_of - timedelta(days=VOLUME_LOOKBACK_DAYS)
        with get_session() as session:
            rows = session.execute(
                select(Price).where(
                    Price.stock_id.in_(stock_ids),
                    Price.date >= cutoff,
                    Price.date <= self.as_of,
                )
            ).scalars().all()
        by_stock: dict[int, list[Price]] = {}
        for price in rows:
            by_stock.setdefault(price.stock_id, []).append(price)
        return by_stock
