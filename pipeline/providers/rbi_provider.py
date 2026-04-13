"""Official India macro provider.

This provider now uses:
- RBI's public home page for the current policy repo rate
- MoSPI's public CPI API for India CPI YoY

The old DBIE JSON path is no longer reliable. MoSPI's CPI endpoint currently
requires legacy TLS negotiation that Python's stdlib/client stack rejects in
some environments, so CPI requests are fetched through `curl` and then parsed.
Results are cached for 24 hours and empty payloads are not cached.
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup
from loguru import logger

from pipeline.providers.cache import JsonCache
from pipeline.providers.dto import MacroReading
from pipeline.providers.errors import DataProviderError

PROVIDER_NAME = "rbi"
TTL = timedelta(hours=24)

_RBI_HOME_URL = "https://www.rbi.org.in/home.aspx"
_MOSPI_CPI_URL = "https://api.mospi.gov.in/api/cpi/getCPIIndex"

_MOSPI_COMBINED_SECTOR_CODE = 3
_MOSPI_GENERAL_GROUP_CODE = 0

_MONTH_CODES = {
    "January": 1,
    "February": 2,
    "March": 3,
    "April": 4,
    "May": 5,
    "June": 6,
    "July": 7,
    "August": 8,
    "September": 9,
    "October": 10,
    "November": 11,
    "December": 12,
}

_SUPPORTED = {
    "INDIA_REPO_RATE",
    "INDIA_CPI_YOY",
}


class RBIProvider:
    def __init__(self, cache: JsonCache | None = None) -> None:
        self.cache = cache or JsonCache(PROVIDER_NAME)

    def get_series(self, indicator: str, start: date, end: date) -> list[MacroReading]:
        if indicator not in _SUPPORTED:
            raise ValueError(
                f"Unknown RBI indicator: '{indicator}'. "
                f"Valid options: {sorted(_SUPPORTED)}"
            )

        cache_args = {"indicator": indicator, "start": str(start), "end": str(end)}
        cached = self.cache.get("series", cache_args, TTL)
        if cached:
            logger.debug(f"[rbi] cache hit: {indicator}")
            return [MacroReading(**r) for r in cached]

        try:
            if indicator == "INDIA_REPO_RATE":
                readings = self._fetch_repo_rate_series(start, end)
            else:
                readings = self._fetch_cpi_yoy_series(start, end)
        except Exception as exc:
            logger.warning(f"[rbi] fetch failed for {indicator}: {exc}. Returning empty.")
            return []

        if readings:
            self.cache.set("series", cache_args, [r.model_dump() for r in readings])
            logger.debug(f"[rbi] fetched {len(readings)} readings for {indicator}")
        return readings

    def _fetch_repo_rate_series(self, start: date, end: date) -> list[MacroReading]:
        response = requests.get(_RBI_HOME_URL, timeout=15.0)
        response.raise_for_status()

        rate = _parse_repo_rate(response.text)
        if rate is None:
            raise DataProviderError("Could not extract RBI policy repo rate")

        as_of = min(date.today(), end)
        if as_of < start:
            return []

        return [MacroReading(indicator="INDIA_REPO_RATE", date=as_of, value=rate)]

    def _fetch_cpi_yoy_series(self, start: date, end: date) -> list[MacroReading]:
        readings: list[MacroReading] = []
        month_cursor = date(start.year, start.month, 1)
        month_end = date(end.year, end.month, 1)

        while month_cursor <= month_end:
            reading = self._fetch_cpi_yoy_month(month_cursor.year, month_cursor.month)
            if reading is not None:
                readings.append(reading)
            month_cursor = _next_month(month_cursor)

        return readings

    def _fetch_cpi_yoy_month(self, year: int, month_code: int) -> MacroReading | None:
        payload = _mospi_get_json(
            {
                "format": "json",
                "year": year,
                "month_code": month_code,
                "sector_code": _MOSPI_COMBINED_SECTOR_CODE,
                "group_code": _MOSPI_GENERAL_GROUP_CODE,
                "page": 1,
            }
        )

        rows = payload.get("data") or []
        row = next(
            (
                item
                for item in rows
                if _is_all_india_general_row(item)
            ),
            None,
        )
        if row is None:
            return None

        inflation = _to_float(row.get("inflation"))
        if inflation is None:
            return None

        return MacroReading(
            indicator="INDIA_CPI_YOY",
            date=date(year, month_code, 1),
            value=inflation,
        )


def _mospi_get_json(params: dict[str, Any]) -> dict[str, Any]:
    url = f"{_MOSPI_CPI_URL}?{urlencode(params)}"
    try:
        completed = subprocess.run(
            [
                "curl",
                "--silent",
                "--show-error",
                "--fail",
                "--location",
                "--max-time",
                "20",
                url,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise DataProviderError("curl is required to fetch MoSPI CPI data") from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        raise DataProviderError(f"MoSPI CPI fetch failed: {detail}") from exc

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise DataProviderError("MoSPI CPI returned invalid JSON") from exc

    if not isinstance(payload, dict):
        raise DataProviderError("MoSPI CPI returned an unexpected payload shape")
    return payload


def _is_all_india_general_row(row: dict[str, Any]) -> bool:
    return (
        str(row.get("state") or "").strip() == "All India"
        and str(row.get("sector") or "").strip() == "Combined"
        and str(row.get("group") or "").strip() == "General"
        and str(row.get("subgroup") or "").strip() == "General-Overall"
    )


def _parse_repo_rate(html: str) -> float | None:
    soup = BeautifulSoup(html, "lxml")
    for th in soup.find_all("th"):
        label = th.get_text(" ", strip=True)
        if "Policy Repo Rate" not in label:
            continue
        td = th.find_next_sibling("td")
        if td is None:
            continue
        return _to_float(td.get_text(" ", strip=True))

    match = re.search(
        r"Policy\s*Repo\s*Rate.*?([0-9]+(?:\.[0-9]+)?)\s*%",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return float(match.group(1)) if match else None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "null":
        return None
    match = re.search(r"-?[0-9]+(?:\.[0-9]+)?", text.replace(",", ""))
    if match is None:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _next_month(current: date) -> date:
    if current.month == 12:
        return date(current.year + 1, 1, 1)
    return date(current.year, current.month + 1, 1)
