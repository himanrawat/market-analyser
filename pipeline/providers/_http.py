"""Shared HTTP helper with retry + backoff for all REST-based providers."""
from __future__ import annotations

from typing import Any

import httpx
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from pipeline.providers.errors import (
    PlanLimitError,
    ProviderRateLimitError,
    ProviderUnavailableError,
)

DEFAULT_TIMEOUT = 30.0
_RETRYABLE = (httpx.TransportError, ProviderUnavailableError)


@retry(
    reraise=True,
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type(_RETRYABLE),
)
def get_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Any:
    """GET a URL and return parsed JSON. Retries on transient errors.
    Maps 429 → ProviderRateLimitError and 5xx → ProviderUnavailableError."""
    try:
        response = httpx.get(url, params=params, headers=headers, timeout=timeout)
    except httpx.TransportError as exc:
        logger.debug(f"Transport error for {url}: {exc}")
        raise ProviderUnavailableError(f"Transport error: {exc}") from exc

    if response.status_code == 429:
        raise ProviderRateLimitError(f"Rate limited by {url}")
    if response.status_code in (402, 403, 404):
        raise PlanLimitError("fmp", url)
    if 500 <= response.status_code < 600:
        raise ProviderUnavailableError(f"{response.status_code} from {url}")
    response.raise_for_status()
    return response.json()
