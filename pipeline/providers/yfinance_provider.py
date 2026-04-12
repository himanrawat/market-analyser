"""yfinance-backed provider. Covers:
- Daily OHLCV for Indian + US stocks (F-1.2)
- India VIX, US VIX, USD/INR, Brent (F-1.6 subset)
- 15-min-delayed quotes for the Refresh Prices button (F-6.7)
- Fallback fundamentals + profile when FMP is unavailable (R-2)

India tickers need the `.NS` (NSE) suffix — handled in `_yf_symbol()`.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
import yfinance as yf
from loguru import logger

from pipeline.db.enums import Country
from pipeline.providers.cache import JsonCache
from pipeline.providers.dto import (
    FundamentalSnapshot,
    MacroReading,
    PriceBar,
    StockProfile,
)
from pipeline.providers.errors import SymbolNotFoundError

PROVIDER_NAME = "yfinance"

# yfinance symbols for macro indicators we care about
MACRO_YF_SYMBOLS: dict[str, str] = {
    "INDIA_VIX": "^INDIAVIX",
    "USD_INR": "INR=X",
    "NIFTY_50": "^NSEI",
    "SP_500": "^GSPC",
    "NASDAQ": "^IXIC",
    "SENSEX": "^BSESN",
    "BRENT_OIL": "BZ=F",
    "GOLD": "GC=F",
    "US_10Y": "^TNX",
}


def _yf_symbol(ticker: str, country: Country) -> str:
    """Primary yfinance symbol — NSE for India, pass-through for US."""
    if country == Country.INDIA and not ticker.endswith((".NS", ".BO")):
        return f"{ticker}.NS"
    return ticker


def _yf_symbols(ticker: str, country: Country) -> list[str]:
    """Ordered list of symbols to try. India: NSE first, BSE fallback."""
    if country == Country.INDIA and not ticker.endswith((".NS", ".BO")):
        return [f"{ticker}.NS", f"{ticker}.BO"]
    return [_yf_symbol(ticker, country)]


class YFinanceProvider:
    """One class covers prices, macro series, and fallback profile/fundamentals."""

    def __init__(self, cache: JsonCache | None = None) -> None:
        self.cache = cache or JsonCache(PROVIDER_NAME)

    # ------------------------------------------------------------------
    # Prices
    # ------------------------------------------------------------------

    def get_daily_ohlcv(
        self, ticker: str, country: Country, start: date, end: date
    ) -> list[PriceBar]:
        symbols = _yf_symbols(ticker, country)
        df = None
        for symbol in symbols:
            logger.debug(f"[yf] OHLCV {symbol} {start}→{end}")
            try:
                df = yf.download(
                    symbol,
                    start=start.isoformat(),
                    end=(end + timedelta(days=1)).isoformat(),
                    progress=False,
                    auto_adjust=False,
                    threads=False,
                )
            except Exception:
                df = None
            if df is not None and not df.empty:
                break

        if df is None or df.empty:
            raise SymbolNotFoundError(ticker, PROVIDER_NAME)

        # yfinance can return a MultiIndex for single-symbol downloads — flatten it
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        bars: list[PriceBar] = []
        for idx, row in df.iterrows():
            bars.append(
                PriceBar(
                    ticker=ticker,
                    country=country,
                    date=idx.date() if hasattr(idx, "date") else idx,
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    adj_close=float(row.get("Adj Close", row["Close"])),
                    volume=int(row["Volume"]) if not pd.isna(row["Volume"]) else 0,
                )
            )
        return bars

    def get_latest_quote(self, ticker: str, country: Country) -> PriceBar:
        """15-minute-delayed last trade. Used by the Refresh Prices button."""
        today = date.today()
        bars = self.get_daily_ohlcv(ticker, country, today - timedelta(days=7), today)
        if not bars:
            raise SymbolNotFoundError(ticker, PROVIDER_NAME)
        return bars[-1]

    # ------------------------------------------------------------------
    # Macro (VIX, FX, indices)
    # ------------------------------------------------------------------

    def get_series(self, indicator: str, start: date, end: date) -> list[MacroReading]:
        symbol = MACRO_YF_SYMBOLS.get(indicator)
        if symbol is None:
            raise ValueError(f"Unknown macro indicator: {indicator}")
        try:
            df = yf.download(
                symbol,
                start=start.isoformat(),
                end=(end + timedelta(days=1)).isoformat(),
                progress=False,
                auto_adjust=False,
                threads=False,
            )
        except Exception as exc:
            raise SymbolNotFoundError(indicator, PROVIDER_NAME) from exc

        if df is None or df.empty:
            return []
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        return [
            MacroReading(
                indicator=indicator,
                date=idx.date() if hasattr(idx, "date") else idx,
                value=float(row["Close"]),
            )
            for idx, row in df.iterrows()
            if not pd.isna(row["Close"])
        ]

    # ------------------------------------------------------------------
    # Profile + fundamentals fallback (info dict is best-effort)
    # ------------------------------------------------------------------

    def get_profile(self, ticker: str, country: Country) -> StockProfile:
        info: dict = {}
        for symbol in _yf_symbols(ticker, country):
            try:
                info = yf.Ticker(symbol).info or {}
            except Exception:
                info = {}
            if info:
                break

        if not info:
            raise SymbolNotFoundError(ticker, PROVIDER_NAME)

        listing_ts = info.get("firstTradeDateEpochUtc")
        listing = date.fromtimestamp(listing_ts) if listing_ts else None

        return StockProfile(
            ticker=ticker,
            country=country,
            name=info.get("longName") or info.get("shortName") or ticker,
            sector=info.get("sector"),
            industry=info.get("industry"),
            currency=info.get("currency") or ("INR" if country == Country.INDIA else "USD"),
            market_cap=info.get("marketCap"),
            listing_date=listing,
            description=info.get("longBusinessSummary"),
        )

    def get_quarterly_fundamentals(
        self, ticker: str, country: Country, limit: int = 20
    ) -> list[FundamentalSnapshot]:
        """Fallback only — FMP is primary. yfinance quarterly data is sparse
        and we only pull the headline fields needed for disqualifier checks."""
        symbol = _yf_symbol(ticker, country)
        t = yf.Ticker(symbol)

        try:
            income = t.quarterly_financials
            balance = t.quarterly_balance_sheet
            cashflow = t.quarterly_cashflow
        except Exception as exc:
            raise SymbolNotFoundError(ticker, PROVIDER_NAME) from exc

        if income is None or income.empty:
            return []

        snapshots: list[FundamentalSnapshot] = []
        for col in list(income.columns)[:limit]:
            fiscal = col.date() if hasattr(col, "date") else col
            revenue = _num(income, "Total Revenue", col)
            net_income = _num(income, "Net Income", col)
            total_debt = _num(balance, "Total Debt", col)
            total_equity = _num(balance, "Stockholders Equity", col)
            ocf = _num(cashflow, "Operating Cash Flow", col)
            capex = _num(cashflow, "Capital Expenditure", col)
            fcf = (ocf + capex) if ocf is not None and capex is not None else None

            debt_eq = (
                total_debt / total_equity
                if total_debt is not None and total_equity and total_equity != 0
                else None
            )

            snapshots.append(
                FundamentalSnapshot(
                    ticker=ticker,
                    country=country,
                    fiscal_date=fiscal,
                    period=fiscal.strftime("%YQ%m"),
                    revenue=revenue,
                    net_income=net_income,
                    total_debt=total_debt,
                    total_equity=total_equity,
                    debt_equity=debt_eq,
                    operating_cash_flow=ocf,
                    free_cash_flow=fcf,
                )
            )
        return snapshots


def _num(df: pd.DataFrame | None, row_label: str, col) -> float | None:
    """Safely pull a cell from a yfinance financials DataFrame."""
    if df is None or df.empty or row_label not in df.index:
        return None
    if col not in df.columns:
        return None
    val = df.at[row_label, col]
    if pd.isna(val):
        return None
    return float(val)
