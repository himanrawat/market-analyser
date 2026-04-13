"""Hardened India HTTP client for NSE and BSE public endpoints.

NSE and BSE are browser-protected public APIs, not stable developer APIs.
This module provides a resilient HTTP session layer with:
- Cookie jar persistence and automatic NSE session priming
- Required browser-like headers
- Conservative per-host rate limiting with jitter
- Retry on transient failures (403, 429, 5xx) with exponential backoff
- Re-prime cookies after a 403 before retrying
- Raw payload snapshot preservation for debugging schema drift
- Defensive JSON parsing (handles non-JSON and empty responses)
"""
from __future__ import annotations

import random
import time
from datetime import UTC, datetime
from typing import Any

import requests
from loguru import logger

_NSE_BASE = "https://www.nseindia.com"
_NSE_PRIME_URL = f"{_NSE_BASE}/companies-listing/corporate-filings-financial-results"
_BSE_BASE = "https://api.bseindia.com"

_NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": _NSE_BASE + "/",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
}

_BSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.bseindia.com/",
    "Origin": "https://www.bseindia.com",
    "Connection": "keep-alive",
}

# Rate limiting: min seconds between consecutive requests per host
_NSE_MIN_INTERVAL = 1.0   # seconds
_BSE_MIN_INTERVAL = 0.8   # seconds
_JITTER_MAX = 0.5         # random extra delay on top of interval

_MAX_RETRIES = 4
_RETRY_INITIAL_WAIT = 2.0
_RETRY_MAX_WAIT = 16.0


class IndiaHTTPError(Exception):
    """Raised when an India exchange endpoint returns a hard error."""


class IndiaHTTPBlockedError(IndiaHTTPError):
    """Raised when the endpoint blocks the request (403, persistent)."""


class IndiaHTTPRateLimitError(IndiaHTTPError):
    """Raised when the endpoint rate-limits the request (429)."""


class IndiaHTTPClient:
    """Resilient HTTP client for both NSE and BSE public APIs.

    Usage:
        client = IndiaHTTPClient()
        payload = client.nse_get_json("/api/quote-equity", params={"symbol": "RELIANCE"})
        payload = client.bse_get_json("/BseIndiaAPI/api/StockReachGraph/w", params={"scripcode": "500325"})
    """

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout: float = 30.0,
        preserve_raw: bool = False,
    ) -> None:
        self._session = session or requests.Session()
        self._timeout = timeout
        self._preserve_raw = preserve_raw
        self._nse_primed = False
        self._nse_last_request: float = 0.0
        self._bse_last_request: float = 0.0
        self._raw_store: list[dict[str, Any]] = []

        self._session.headers.update(_NSE_HEADERS)

    # ------------------------------------------------------------------
    # Public NSE interface
    # ------------------------------------------------------------------

    def nse_get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        retry_on_403: bool = True,
    ) -> Any:
        """GET an NSE API path and return parsed JSON.

        Handles session priming, cookie maintenance, rate limiting, and retries.
        """
        self._nse_prime()
        return self._get_json_with_retry(
            base=_NSE_BASE,
            path=path,
            params=params,
            headers=_NSE_HEADERS,
            last_request_attr="_nse_last_request",
            min_interval=_NSE_MIN_INTERVAL,
            retry_on_403=retry_on_403,
            re_prime_fn=self._nse_reprime,
        )

    # ------------------------------------------------------------------
    # Public BSE interface
    # ------------------------------------------------------------------

    def bse_get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """GET a BSE API path and return parsed JSON."""
        return self._get_json_with_retry(
            base=_BSE_BASE,
            path=path,
            params=params,
            headers=_BSE_HEADERS,
            last_request_attr="_bse_last_request",
            min_interval=_BSE_MIN_INTERVAL,
            retry_on_403=False,
            re_prime_fn=None,
        )

    # ------------------------------------------------------------------
    # Raw payload access (only populated when preserve_raw=True)
    # ------------------------------------------------------------------

    def drain_raw_payloads(self) -> list[dict[str, Any]]:
        """Return and clear the accumulated raw payload log."""
        result = list(self._raw_store)
        self._raw_store.clear()
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _nse_prime(self) -> None:
        if self._nse_primed:
            return
        self._nse_reprime()

    def _nse_reprime(self) -> None:
        logger.debug("Priming NSE session (cookie refresh)...")
        try:
            resp = self._session.get(
                _NSE_PRIME_URL,
                headers=_NSE_HEADERS,
                timeout=self._timeout,
            )
            resp.raise_for_status()
            self._nse_primed = True
            logger.debug(f"NSE session primed — cookies: {list(self._session.cookies.keys())}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"NSE session priming failed: {exc}")
            self._nse_primed = False

    def _throttle(self, attr: str, min_interval: float) -> None:
        last = getattr(self, attr, 0.0)
        elapsed = time.monotonic() - last
        if elapsed < min_interval:
            sleep_time = min_interval - elapsed + random.uniform(0, _JITTER_MAX)
            time.sleep(sleep_time)
        setattr(self, attr, time.monotonic())

    def _get_json_with_retry(
        self,
        *,
        base: str,
        path: str,
        params: dict[str, Any] | None,
        headers: dict[str, str],
        last_request_attr: str,
        min_interval: float,
        retry_on_403: bool,
        re_prime_fn: Any,
    ) -> Any:
        url = base.rstrip("/") + path
        wait = _RETRY_INITIAL_WAIT

        for attempt in range(1, _MAX_RETRIES + 1):
            self._throttle(last_request_attr, min_interval)

            try:
                resp = self._session.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=self._timeout,
                )
            except requests.RequestException as exc:
                logger.debug(f"[india_http] transport error for {url} (attempt {attempt}): {exc}")
                if attempt < _MAX_RETRIES:
                    time.sleep(wait)
                    wait = min(wait * 2, _RETRY_MAX_WAIT)
                    continue
                raise IndiaHTTPError(f"Transport error after {_MAX_RETRIES} attempts: {exc}") from exc

            if resp.status_code == 429:
                logger.warning(f"[india_http] rate limited by {url} (attempt {attempt})")
                if attempt < _MAX_RETRIES:
                    time.sleep(wait * 2)
                    wait = min(wait * 2, _RETRY_MAX_WAIT)
                    continue
                raise IndiaHTTPRateLimitError(f"Rate limited by {url}")

            if resp.status_code == 403:
                if retry_on_403 and re_prime_fn and attempt < _MAX_RETRIES:
                    logger.debug(f"[india_http] 403 on {url} — re-priming session (attempt {attempt})")
                    re_prime_fn()
                    time.sleep(wait)
                    wait = min(wait * 2, _RETRY_MAX_WAIT)
                    continue
                raise IndiaHTTPBlockedError(f"403 Forbidden: {url}")

            if 500 <= resp.status_code < 600:
                logger.debug(f"[india_http] {resp.status_code} from {url} (attempt {attempt})")
                if attempt < _MAX_RETRIES:
                    time.sleep(wait)
                    wait = min(wait * 2, _RETRY_MAX_WAIT)
                    continue
                raise IndiaHTTPError(f"{resp.status_code} from {url}")

            # Non-2xx other than handled above
            if not resp.ok:
                raise IndiaHTTPError(f"HTTP {resp.status_code} from {url}")

            # Try JSON parse
            content_type = resp.headers.get("Content-Type", "")
            if not resp.content:
                logger.debug(f"[india_http] empty response from {url}")
                return None

            try:
                payload = resp.json()
            except ValueError:
                if "text/html" in content_type:
                    # NSE sometimes returns HTML when session expires
                    if retry_on_403 and re_prime_fn and attempt < _MAX_RETRIES:
                        logger.debug(f"[india_http] HTML response from {url} — re-priming")
                        re_prime_fn()
                        time.sleep(wait)
                        wait = min(wait * 2, _RETRY_MAX_WAIT)
                        continue
                logger.debug(f"[india_http] non-JSON response from {url}: {resp.text[:200]}")
                return None

            if self._preserve_raw:
                self._raw_store.append({
                    "url": url,
                    "params": params,
                    "fetched_at": datetime.now(UTC).isoformat(),
                    "status_code": resp.status_code,
                    "payload": payload,
                })

            return payload

        raise IndiaHTTPError(f"Exhausted retries for {url}")
