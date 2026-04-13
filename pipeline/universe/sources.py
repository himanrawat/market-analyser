"""Constituent list fetchers for each index.

Sources:
- S&P 500:  SSGA SPY ETF daily holdings file (official, free, no API key)
- S&P 100:  Top 100 holdings by weight from the same SPY file
- Nifty 500: NSE India website CSV download (official, publicly accessible)
- Nifty 50:  NSE website (subset used for macro regime check)

SSGA publishes SPY holdings as a public Excel file updated daily. It contains
ticker, name, weight, and sector — no API key required. The S&P 100 is derived
by taking the 100 highest-weight holdings from SPY (same companies, same list).

Sector/industry gaps are backfilled by UniverseLoader via the routed profile
lane for each market (official India metadata first, vendor-backed US profile
lane for US stocks).
"""
from __future__ import annotations

import io
from datetime import date

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

# SSGA publishes SPY holdings daily — free, no API key, institutionally maintained
_SSGA_SPY_URL = (
    "https://www.ssga.com/us/en/individual/etfs/library-content/products/"
    "fund-data/etfs/us/holdings-daily-us-en-spy.xlsx"
)


def _fetch_spy_holdings() -> pd.DataFrame:
    """Download and parse SPY holdings Excel file from SSGA.

    Returns a DataFrame with columns: ticker, name, weight, sector.
    Rows are sorted by weight descending (largest holdings first).
    """
    try:
        resp = requests.get(_SSGA_SPY_URL, headers=_HEADERS, timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        raise RuntimeError(f"Failed to download SPY holdings from SSGA: {exc}") from exc

    # SSGA Excel has a few metadata rows before the actual table.
    # We find the header row by searching for a row containing "Ticker".
    raw = pd.read_excel(io.BytesIO(resp.content), header=None)
    header_row = None
    for i, row in raw.iterrows():
        if any(str(v).strip().lower() == "ticker" for v in row.values):
            header_row = i
            break

    if header_row is None:
        raise RuntimeError("Could not locate 'Ticker' header in SSGA SPY holdings file.")

    df = pd.read_excel(io.BytesIO(resp.content), header=header_row)
    df.columns = [str(c).strip().lower() for c in df.columns]

    # Keep only rows with a valid ticker (drop cash/cash equivalents at the bottom)
    df = df[df["ticker"].notna() & (df["ticker"].astype(str).str.strip() != "-")]
    df = df[df["ticker"].astype(str).str.strip() != ""]

    # Normalize column access — SSGA names vary slightly between file versions
    weight_col = next((c for c in df.columns if "weight" in c), None)
    sector_col = next((c for c in df.columns if "sector" in c), None)
    name_col = next((c for c in df.columns if c in ("name", "security name")), None)

    result = pd.DataFrame()
    result["ticker"] = df["ticker"].astype(str).str.strip()
    result["name"] = df[name_col].astype(str).str.strip() if name_col else None
    result["weight"] = pd.to_numeric(df[weight_col], errors="coerce") if weight_col else 0.0
    result["sector"] = df[sector_col].astype(str).str.strip().replace("nan", None) if sector_col else None

    return result.sort_values("weight", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# S&P 500
# ---------------------------------------------------------------------------


def fetch_sp500() -> list[UniverseConstituent]:
    """Load S&P 500 constituent list from SSGA SPY ETF daily holdings file.

    No API key required. Sector gaps are backfilled later by UniverseLoader.
    """
    logger.info("Fetching S&P 500 constituents from SSGA SPY holdings…")
    df = _fetch_spy_holdings()

    today = date.today()
    constituents = [
        UniverseConstituent(
            index_name=IndexName.SP_500,
            ticker=row["ticker"],
            country=Country.US,
            name=row["name"] or None,
            sector=row["sector"] or None,
            as_of=today,
        )
        for _, row in df.iterrows()
        if row["ticker"]
    ]
    logger.info(f"S&P 500: {len(constituents)} constituents")
    return constituents


# ---------------------------------------------------------------------------
# S&P 100
# ---------------------------------------------------------------------------


def fetch_sp100() -> list[UniverseConstituent]:
    """Derive S&P 100 by taking the top 100 holdings by weight from SPY.

    The S&P 100 is the 100 largest companies in the S&P 500 — identical to
    the top-100 SPY holdings by index weight.
    """
    logger.info("Fetching S&P 100 (top-100 SPY holdings by weight) from SSGA…")
    df = _fetch_spy_holdings().head(100)

    today = date.today()
    constituents = [
        UniverseConstituent(
            index_name=IndexName.SP_100,
            ticker=row["ticker"],
            country=Country.US,
            name=row["name"] or None,
            sector=row["sector"] or None,
            as_of=today,
        )
        for _, row in df.iterrows()
        if row["ticker"]
    ]
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
    except Exception as exc:
        raise RuntimeError(f"Failed to fetch Nifty 500 from NSE: {exc}") from exc

    import pandas as pd
    df = pd.read_csv(io.StringIO(resp.text))

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
                isin=str(row.get("ISIN Code") or "").strip() or None,
                nse_symbol=ticker,
                as_of=today,
            )
        )
    logger.info(f"Nifty 500: {len(constituents)} constituents")
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
    except Exception as exc:
        raise RuntimeError(f"Failed to fetch Nifty 50 list from NSE: {exc}") from exc

    import pandas as pd
    df = pd.read_csv(io.StringIO(resp.text))

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
                isin=str(row.get("ISIN Code") or "").strip() or None,
                nse_symbol=ticker,
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
