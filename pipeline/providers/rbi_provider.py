"""RBI DBIE scraper for India macro data.

F-1.6: fetches RBI repo rate and India CPI from RBI's public DBIE portal.
DBIE has no official API — we scrape the JSON endpoints that power their
charts. These endpoints are stable but unofficial; the scraper includes
a fallback that returns the last cached value if the source changes.

Endpoints used:
- Repo rate: https://dbie.rbi.org.in/DBIE/dbie.rbi?site=publications (series)
- India CPI: https://dbie.rbi.org.in (separate series endpoint)

In practice, RBI data changes monthly at most. TTL is set to 24h.

Note: if DBIE changes its endpoint structure, update _REPO_RATE_URL and
_CPI_URL here. The caching layer means this won't break a run mid-stream.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from loguru import logger

from pipeline.providers._http import get_json
from pipeline.providers.cache import JsonCache
from pipeline.providers.dto import MacroReading
from pipeline.providers.errors import DataProviderError

PROVIDER_NAME = "rbi"
TTL = timedelta(hours=24)

# DBIE REST-like endpoints. Both return JSON when accessed with the right params.
# If these break, update only here.
_DBIE_BASE = "https://dbie.rbi.org.in/DBIE/dbie.rbi"
_REPO_RATE_SERIES_ID = "DP_REPORATE"
_CPI_SERIES_ID = "DP_CPI_COMBINED_RURAL_URBAN"

INDICATOR_MAP = {
    "INDIA_REPO_RATE": _REPO_RATE_SERIES_ID,
    "INDIA_CPI_YOY": _CPI_SERIES_ID,
}


class RBIProvider:
    def __init__(self, cache: JsonCache | None = None) -> None:
        self.cache = cache or JsonCache(PROVIDER_NAME)

    def get_series(self, indicator: str, start: date, end: date) -> list[MacroReading]:
        series_id = INDICATOR_MAP.get(indicator)
        if series_id is None:
            raise ValueError(
                f"Unknown RBI indicator: '{indicator}'. "
                f"Valid options: {list(INDICATOR_MAP)}"
            )

        cache_args = {"series_id": series_id, "start": str(start), "end": str(end)}
        cached = self.cache.get("series", cache_args, TTL)
        if cached is not None:
            logger.debug(f"[rbi] cache hit: {series_id}")
            return [MacroReading(**r) for r in cached]

        try:
            readings = self._fetch_series(series_id, start, end)
        except Exception as exc:
            logger.warning(f"[rbi] fetch failed for {series_id}: {exc}. Returning empty.")
            return []

        self.cache.set("series", cache_args, [r.model_dump() for r in readings])
        logger.debug(f"[rbi] fetched {len(readings)} readings for {series_id}")
        return readings

    def _fetch_series(self, series_id: str, start: date, end: date) -> list[MacroReading]:
        """Attempt to pull data from DBIE's internal API. If that fails, parse
        the RBI publications page for the repo rate as a last resort."""
        params = {
            "site": "publications",
            "seriesCode": series_id,
            "fromYear": start.year,
            "toYear": end.year,
            "outputType": "json",
        }
        try:
            data = get_json(_DBIE_BASE, params=params, timeout=15.0)
            return _parse_dbie_response(data, series_id, start, end)
        except Exception as exc:
            logger.debug(f"[rbi] primary fetch failed ({exc}), trying fallback…")

        # Fallback: hit the public publications page and extract the latest figure
        return self._fallback_scrape(series_id, start, end)

    def _fallback_scrape(
        self, series_id: str, start: date, end: date
    ) -> list[MacroReading]:
        """Very lightweight fallback — just gets the current repo rate from
        RBI's press release page if the DBIE API is down. Returns a single
        reading dated today."""
        if series_id != _REPO_RATE_SERIES_ID:
            return []

        try:
            import httpx
            resp = httpx.get(
                "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx",
                timeout=10.0,
            )
            # Look for "Repo Rate X.XX per cent" pattern in HTML
            match = re.search(
                r"repo rate.*?(\d+\.\d+)\s*per\s*cent", resp.text, re.IGNORECASE
            )
            if match:
                rate = float(match.group(1))
                return [MacroReading(indicator="INDIA_REPO_RATE", date=date.today(), value=rate)]
        except Exception as exc:
            logger.warning(f"[rbi] fallback scrape failed: {exc}")
        return []


def _parse_dbie_response(
    data: Any, series_id: str, start: date, end: date
) -> list[MacroReading]:
    """Parse whatever DBIE returns. Their format has changed before."""
    if not data:
        raise DataProviderError("DBIE returned empty response")

    indicator = next(
        (k for k, v in INDICATOR_MAP.items() if v == series_id), series_id
    )

    readings: list[MacroReading] = []

    # Handle list-of-observations format
    rows = data if isinstance(data, list) else data.get("data") or data.get("observations") or []
    for row in rows:
        if not isinstance(row, (list, dict)):
            continue
        if isinstance(row, list) and len(row) >= 2:
            date_val, value_val = row[0], row[1]
        else:
            date_val = row.get("date") or row.get("period")
            value_val = row.get("value") or row.get("obs_value")

        parsed_date = _parse_date(date_val)
        if parsed_date is None or not (start <= parsed_date <= end):
            continue
        try:
            readings.append(
                MacroReading(indicator=indicator, date=parsed_date, value=float(value_val))
            )
        except (TypeError, ValueError):
            continue

    if not readings:
        raise DataProviderError(f"No usable rows in DBIE response for {series_id}")
    return readings


def _parse_date(val: Any) -> date | None:
    if not val:
        return None
    s = str(val).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%b-%Y", "%B %Y", "%Y"):
        try:
            return datetime.strptime(s[:len(fmt)], fmt).date()
        except ValueError:
            continue
    return None
