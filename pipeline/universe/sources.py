"""Constituent list fetchers for each index.

Sources (all free, no API key needed):
- S&P 500:  Wikipedia table (stable, updated within days of changes)
- Nifty 500: NSE India website CSV download (official, publicly accessible)
- Nifty 50:  NSE website (subset used for macro regime check)
- S&P 100:   Wikipedia table

These are used only for the ticker+sector list. Prices and fundamentals
come from yfinance/FMP. The quarterly refresh cadence means staleness of
a few days is completely acceptable.
"""
from __future__ import annotations

import io
from datetime import date
from typing import Any

import pandas as pd
import requests
from loguru import logger

from pipeline.db.enums import Country, IndexName
from pipeline.providers.dto import UniverseConstituent

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


# ---------------------------------------------------------------------------
# S&P 500
# ---------------------------------------------------------------------------


def fetch_sp500() -> list[UniverseConstituent]:
    """Scrape the S&P 500 constituent table from Wikipedia."""
    logger.info("Fetching S&P 500 constituents from Wikipedia…")
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    try:
        tables = pd.read_html(url, attrs={"id": "constituents"})
        df = tables[0]
    except Exception as exc:
        raise RuntimeError(f"Failed to fetch S&P 500 list from Wikipedia: {exc}") from exc

    today = date.today()
    constituents: list[UniverseConstituent] = []
    for _, row in df.iterrows():
        ticker = str(row.get("Symbol") or row.get("Ticker symbol") or "").strip()
        name = str(row.get("Security") or row.get("Company") or "").strip()
        sector = str(row.get("GICS Sector") or row.get("Sector") or "").strip() or None
        industry = str(row.get("GICS Sub-Industry") or row.get("Sub-Industry") or "").strip() or None
        if not ticker:
            continue
        # Wikipedia uses BRK.B / BRK.A — yfinance needs BRK-B
        ticker = ticker.replace(".", "-")
        constituents.append(
            UniverseConstituent(
                index_name=IndexName.SP_500,
                ticker=ticker,
                country=Country.US,
                name=name,
                sector=sector,
                industry=industry,
                as_of=today,
            )
        )
    logger.info(f"S&P 500: {len(constituents)} constituents")
    return constituents


# ---------------------------------------------------------------------------
# S&P 100
# ---------------------------------------------------------------------------


def fetch_sp100() -> list[UniverseConstituent]:
    """Scrape the S&P 100 list from Wikipedia."""
    logger.info("Fetching S&P 100 constituents from Wikipedia…")
    url = "https://en.wikipedia.org/wiki/S%26P_100"
    try:
        tables = pd.read_html(url)
        # Find the table with a Symbol/Ticker column
        df = next(
            t for t in tables
            if any(c in str(t.columns.tolist()) for c in ["Symbol", "Ticker"])
        )
    except Exception as exc:
        raise RuntimeError(f"Failed to fetch S&P 100 list from Wikipedia: {exc}") from exc

    today = date.today()
    constituents: list[UniverseConstituent] = []
    for _, row in df.iterrows():
        ticker = str(row.get("Symbol") or row.get("Ticker") or "").strip().replace(".", "-")
        name = str(row.get("Name") or row.get("Company") or "").strip()
        sector = str(row.get("Sector") or row.get("GICS Sector") or "").strip() or None
        if not ticker or ticker == "nan":
            continue
        constituents.append(
            UniverseConstituent(
                index_name=IndexName.SP_100,
                ticker=ticker,
                country=Country.US,
                name=name,
                sector=sector,
                as_of=today,
            )
        )
    logger.info(f"S&P 100: {len(constituents)} constituents")
    return constituents


# ---------------------------------------------------------------------------
# Nifty 500
# ---------------------------------------------------------------------------

_NSE_NIFTY500_URL = (
    "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
)


def fetch_nifty500() -> list[UniverseConstituent]:
    """Download the official Nifty 500 CSV from NSE India archives."""
    logger.info("Fetching Nifty 500 constituents from NSE…")
    try:
        resp = requests.get(_NSE_NIFTY500_URL, headers=_HEADERS, timeout=20)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
    except Exception as exc:
        logger.warning(f"NSE primary fetch failed: {exc}. Trying fallback…")
        return _fetch_nifty500_wikipedia_fallback()

    today = date.today()
    constituents: list[UniverseConstituent] = []
    for _, row in df.iterrows():
        # NSE CSV columns: Company Name, Industry, Symbol, Series, ISIN Code
        ticker = str(row.get("Symbol") or "").strip()
        name = str(row.get("Company Name") or "").strip()
        sector = str(row.get("Industry") or "").strip() or None
        if not ticker:
            continue
        constituents.append(
            UniverseConstituent(
                index_name=IndexName.NIFTY_500,
                ticker=ticker,
                country=Country.INDIA,
                name=name,
                sector=sector,
                as_of=today,
            )
        )
    logger.info(f"Nifty 500: {len(constituents)} constituents")
    return constituents


def _fetch_nifty500_wikipedia_fallback() -> list[UniverseConstituent]:
    """Fallback: scrape from Wikipedia if NSE is unavailable."""
    url = "https://en.wikipedia.org/wiki/NIFTY_500"
    today = date.today()
    try:
        tables = pd.read_html(url)
        df = next(t for t in tables if "Symbol" in t.columns or "Ticker" in t.columns)
    except Exception as exc:
        raise RuntimeError(f"Both NSE and Wikipedia Nifty 500 sources failed: {exc}") from exc

    constituents: list[UniverseConstituent] = []
    for _, row in df.iterrows():
        ticker = str(row.get("Symbol") or row.get("Ticker") or "").strip()
        name = str(row.get("Company") or row.get("Name") or "").strip()
        sector = str(row.get("Sector") or "").strip() or None
        if not ticker or ticker == "nan":
            continue
        constituents.append(
            UniverseConstituent(
                index_name=IndexName.NIFTY_500,
                ticker=ticker,
                country=Country.INDIA,
                name=name,
                sector=sector,
                as_of=today,
            )
        )
    logger.info(f"Nifty 500 (Wikipedia fallback): {len(constituents)} constituents")
    return constituents


# ---------------------------------------------------------------------------
# Nifty 50
# ---------------------------------------------------------------------------

_NSE_NIFTY50_URL = (
    "https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv"
)


def fetch_nifty50() -> list[UniverseConstituent]:
    """Download the official Nifty 50 CSV from NSE India."""
    logger.info("Fetching Nifty 50 constituents from NSE…")
    try:
        resp = requests.get(_NSE_NIFTY50_URL, headers=_HEADERS, timeout=20)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
    except Exception as exc:
        raise RuntimeError(f"Failed to fetch Nifty 50 list: {exc}") from exc

    today = date.today()
    constituents: list[UniverseConstituent] = []
    for _, row in df.iterrows():
        ticker = str(row.get("Symbol") or "").strip()
        name = str(row.get("Company Name") or "").strip()
        sector = str(row.get("Industry") or "").strip() or None
        if not ticker:
            continue
        constituents.append(
            UniverseConstituent(
                index_name=IndexName.NIFTY_50,
                ticker=ticker,
                country=Country.INDIA,
                name=name,
                sector=sector,
                as_of=today,
            )
        )
    logger.info(f"Nifty 50: {len(constituents)} constituents")
    return constituents


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_FETCHERS = {
    IndexName.SP_500: fetch_sp500,
    IndexName.SP_100: fetch_sp100,
    IndexName.NIFTY_500: fetch_nifty500,
    IndexName.NIFTY_50: fetch_nifty50,
}


def fetch_constituents(index_name: IndexName) -> list[UniverseConstituent]:
    fetcher = _FETCHERS.get(index_name)
    if fetcher is None:
        raise ValueError(f"No constituent fetcher for index: {index_name}")
    return fetcher()
