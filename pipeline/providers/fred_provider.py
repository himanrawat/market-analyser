"""FRED (Federal Reserve Economic Data) provider.

Covers US macro series: Fed funds rate, CPI, GDP, 10-year treasury yield.
Uses the `fredapi` Python wrapper — simpler than raw HTTP for FRED's
observation-series format.

All series IDs: https://fred.stlouisfed.org/series/<series_id>
"""
from __future__ import annotations

from datetime import date, timedelta

from loguru import logger

from pipeline.config import settings
from pipeline.providers.cache import JsonCache
from pipeline.providers.dto import MacroReading
from pipeline.providers.errors import DataProviderError, MissingApiKeyError

PROVIDER_NAME = "fred"
TTL = timedelta(days=1)

# Series we care about. Names must match what the pipeline requests by indicator.
FRED_SERIES: dict[str, str] = {
    "FEDFUNDS": "FEDFUNDS",          # Fed funds effective rate (monthly)
    "US_CPI_YOY": "CPIAUCSL",       # CPI, all items (monthly)
    "US_10Y": "DGS10",              # 10-year treasury constant maturity (daily)
    "US_GDP_GROWTH": "A191RL1Q225SBEA",  # Real GDP growth rate (quarterly)
    "US_UNEMPLOYMENT": "UNRATE",    # Unemployment rate (monthly)
}


class FREDProvider:
    def __init__(self, cache: JsonCache | None = None) -> None:
        self.cache = cache or JsonCache(PROVIDER_NAME)

    def _require_key(self) -> str:
        key = settings.fred_api_key
        if not key:
            raise MissingApiKeyError(PROVIDER_NAME, "FRED_API_KEY")
        return key

    def get_series(self, indicator: str, start: date, end: date) -> list[MacroReading]:
        """Fetch a named FRED series. `indicator` must be a key in FRED_SERIES."""
        series_id = FRED_SERIES.get(indicator)
        if series_id is None:
            raise ValueError(
                f"Unknown FRED indicator: '{indicator}'. "
                f"Valid options: {list(FRED_SERIES)}"
            )

        cache_args = {"series_id": series_id, "start": str(start), "end": str(end)}
        cached = self.cache.get("series", cache_args, TTL)
        if cached is not None:
            logger.debug(f"[fred] cache hit: {series_id}")
            return [MacroReading(**r) for r in cached]

        key = self._require_key()
        try:
            from fredapi import Fred  # imported lazily — not installed in test env

            fred = Fred(api_key=key)
            series = fred.get_series(
                series_id,
                observation_start=start.isoformat(),
                observation_end=end.isoformat(),
            )
        except ImportError as exc:
            raise DataProviderError(
                "fredapi not installed. Run: pip install fredapi"
            ) from exc
        except Exception as exc:
            raise DataProviderError(f"FRED fetch failed for {series_id}: {exc}") from exc

        readings = [
            MacroReading(indicator=indicator, date=ts.date(), value=float(val))
            for ts, val in series.items()
            if val is not None and str(val) != "nan"
        ]

        self.cache.set("series", cache_args, [r.model_dump() for r in readings])
        logger.debug(f"[fred] fetched {len(readings)} readings for {series_id}")
        return readings
