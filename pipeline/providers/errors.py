"""Exception hierarchy for data providers. Keeps call-site handling uniform."""
from __future__ import annotations


class DataProviderError(Exception):
    """Base class for all data provider failures."""


class MissingApiKeyError(DataProviderError):
    """Raised when a provider is called without its required API key configured."""

    def __init__(self, provider: str, env_var: str) -> None:
        super().__init__(
            f"{provider} requires {env_var} to be set in .env. "
            f"Get a key and add it before retrying."
        )
        self.provider = provider
        self.env_var = env_var


class SymbolNotFoundError(DataProviderError):
    """Raised when the vendor returns no data for a ticker."""

    def __init__(self, ticker: str, provider: str) -> None:
        super().__init__(f"{provider} returned no data for symbol '{ticker}'.")
        self.ticker = ticker
        self.provider = provider


class ProviderRateLimitError(DataProviderError):
    """Raised when the vendor responds with HTTP 429 or the equivalent."""


class ProviderUnavailableError(DataProviderError):
    """Raised when the vendor is unreachable or returns 5xx after retries."""


class PlanLimitError(DataProviderError):
    """Raised when the endpoint requires a higher subscription tier (HTTP 402/403)."""

    def __init__(self, provider: str, endpoint: str) -> None:
        super().__init__(
            f"{provider}: endpoint '{endpoint}' is not available on the current plan."
        )
        self.provider = provider
        self.endpoint = endpoint
