"""Financial Modeling Prep (FMP) provider — stable API.

FMP migrated all endpoints from /api/v3/ (legacy, now 403) to /stable/
(query-parameter style). The Starter plan supports:
  - profile, income-statement, balance-sheet-statement, cash-flow-statement
    for US tickers ✓
  - ratios-ttm, key-metrics-ttm for all tickers ✓
  - earnings calendar ✓
  - dividends ✓
  - news: fmp-articles, news/general-latest, news/stock-latest, news/stock ✓
  - Indian stock fundamentals (income-stmt etc.) require a higher plan → 402;
    the registry catches PlanLimitError and falls back to yfinance.
  - index constituents (sp500_constituent, sp100_constituent) require Professional plan → NOT used.

All responses are cached via `JsonCache` with per-endpoint TTLs.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from loguru import logger

from pipeline.config import settings
from pipeline.db.enums import Country, EventType, NewsStream
from pipeline.providers._http import get_json
from pipeline.providers.cache import JsonCache
from pipeline.providers.dto import (
    AnalystForecastSnapshot,
    EventRecord,
    FundamentalSnapshot,
    NewsArticle,
    QuarterlyEstimate,
    StockProfile,
)
from pipeline.providers.errors import (
    DataProviderError,
    MissingApiKeyError,
    PlanLimitError,
    SymbolNotFoundError,
)

PROVIDER_NAME = "fmp"
BASE_STABLE = "https://financialmodelingprep.com/stable"

TTL_PROFILE = timedelta(hours=24)
TTL_FUNDAMENTALS = timedelta(days=30)
TTL_NEWS = timedelta(minutes=30)
TTL_EVENTS = timedelta(hours=6)
TTL_ANALYST = timedelta(hours=12)
TTL_PEERS = timedelta(days=7)


def _fmp_symbol(ticker: str, country: Country) -> str:
    if country != Country.US:
        raise DataProviderError(
            "FMP is now restricted to the US lane in this repository."
        )
    return ticker


class FMPProvider:
    def __init__(self, cache: JsonCache | None = None) -> None:
        self.cache = cache or JsonCache(PROVIDER_NAME)

    # ------------------------------------------------------------------
    # Shared request helper
    # ------------------------------------------------------------------

    def _require_key(self) -> str:
        key = settings.fmp_api_key
        if not key:
            raise MissingApiKeyError(PROVIDER_NAME, "FMP_API_KEY")
        return key

    def _get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        cache_ttl: timedelta | None = None,
    ) -> Any:
        key = self._require_key()
        params = {**(params or {}), "apikey": key}

        cache_args = {k: v for k, v in params.items() if k != "apikey"}
        cache_args["path"] = path

        if cache_ttl is not None:
            cached = self.cache.get(path, cache_args, cache_ttl)
            if cached is not None:
                logger.debug(f"[fmp] cache hit: {path} {cache_args}")
                return cached

        data = get_json(f"{BASE_STABLE}/{path}", params=params)
        if cache_ttl is not None:
            self.cache.set(path, cache_args, data)
        return data

    # ------------------------------------------------------------------
    # Profile
    # ------------------------------------------------------------------

    def get_profile(self, ticker: str, country: Country) -> StockProfile:
        symbol = _fmp_symbol(ticker, country)
        data = self._get("profile", params={"symbol": symbol}, cache_ttl=TTL_PROFILE)
        if not data:
            raise SymbolNotFoundError(ticker, PROVIDER_NAME)
        row = data[0] if isinstance(data, list) else data

        listing = _parse_date(row.get("ipoDate"))
        return StockProfile(
            ticker=ticker,
            country=country,
            name=row.get("companyName") or ticker,
            sector=row.get("sector"),
            industry=row.get("industry"),
            currency=row.get("currency") or ("INR" if country == Country.INDIA else "USD"),
            market_cap=_num(row.get("marketCap")),
            listing_date=listing,
            description=row.get("description"),
        )

    # ------------------------------------------------------------------
    # Quarterly fundamentals
    # Starter plan: US quarterly statements ✓ | Indian statements → PlanLimitError
    # Ratios/key-metrics: TTM only (quarterly is premium)
    # ------------------------------------------------------------------

    def get_quarterly_fundamentals(
        self, ticker: str, country: Country, limit: int = 20
    ) -> list[FundamentalSnapshot]:
        symbol = _fmp_symbol(ticker, country)
        params_q = {"symbol": symbol, "period": "quarter", "limit": limit}

        # These raise PlanLimitError for Indian tickers → caught by registry
        income = self._get("income-statement", params=params_q, cache_ttl=TTL_FUNDAMENTALS) or []
        balance = self._get("balance-sheet-statement", params=params_q, cache_ttl=TTL_FUNDAMENTALS) or []
        cashflow = self._get("cash-flow-statement", params=params_q, cache_ttl=TTL_FUNDAMENTALS) or []

        ttm_ratios = self._fetch_ttm("ratios-ttm", symbol)
        ttm_km = self._fetch_ttm("key-metrics-ttm", symbol)

        by_date = _index_by_date(income, balance, cashflow)
        return [
            s for s in (
                _build_snapshot(ticker, country, i, fiscal_str, parts, ttm_ratios, ttm_km)
                for i, (fiscal_str, parts) in enumerate(sorted(by_date.items(), reverse=True))
            )
            if s is not None
        ]

    def _fetch_ttm(self, endpoint: str, symbol: str) -> dict[str, Any]:
        """Fetch a TTM endpoint; return empty dict if plan limit hit."""
        try:
            result = self._get(endpoint, params={"symbol": symbol}, cache_ttl=TTL_FUNDAMENTALS) or []
            return (result[0] if isinstance(result, list) and result else result) or {}
        except PlanLimitError:
            return {}

    # ------------------------------------------------------------------
    # News — stock-specific news is restricted on Starter; general news
    # also moved off v4. Both fall back gracefully at call site.
    # ------------------------------------------------------------------

    def get_stock_news(
        self, ticker: str, country: Country, since: datetime, limit: int = 50
    ) -> list[NewsArticle]:
        """Symbol-specific stock news. Endpoint: /stable/news/stock?symbols=AAPL"""
        symbol = _fmp_symbol(ticker, country)
        data = self._get(
            "news/stock",
            params={"symbols": symbol, "limit": limit},
            cache_ttl=TTL_NEWS,
        ) or []
        articles = [self._to_news(row, ticker, country) for row in data]
        return [a for a in articles if a and a.published_at >= since]

    def get_stock_news_latest(self, since: datetime, limit: int = 50) -> list[NewsArticle]:
        """Latest stock news across all tickers. Endpoint: /stable/news/stock-latest"""
        data = self._get(
            "news/stock-latest",
            params={"limit": limit},
            cache_ttl=TTL_NEWS,
        ) or []
        articles = [self._to_news(row, None, None) for row in data]
        return [a for a in articles if a and a.published_at >= since]

    def get_general_news(self, since: datetime, limit: int = 100) -> list[NewsArticle]:
        """General market news. Endpoint: /stable/news/general-latest"""
        data = self._get(
            "news/general-latest",
            params={"limit": limit},
            cache_ttl=TTL_NEWS,
        ) or []
        articles = [self._to_news(row, None, None) for row in data]
        return [a for a in articles if a and a.published_at >= since]

    def get_fmp_articles(self, since: datetime, limit: int = 20) -> list[NewsArticle]:
        """FMP's own market analysis articles. Endpoint: /stable/fmp-articles"""
        data = self._get(
            "fmp-articles",
            params={"page": 0, "limit": limit},
            cache_ttl=TTL_NEWS,
        ) or []
        # fmp-articles uses 'date' and 'link' instead of 'publishedDate' and 'url'
        articles = [self._to_news(row, None, None) for row in data]
        return [a for a in articles if a and a.published_at >= since]

    # ------------------------------------------------------------------
    # Analyst forecasts / peers
    # ------------------------------------------------------------------

    def get_analyst_forecast(
        self,
        ticker: str,
        country: Country,
        *,
        limit: int = 4,
        current_price: float | None = None,
    ) -> AnalystForecastSnapshot | None:
        symbol = _fmp_symbol(ticker, country)

        consensus = self._get(
            "price-target-consensus",
            params={"symbol": symbol},
            cache_ttl=TTL_ANALYST,
        ) or []
        grades = self._get(
            "grades-consensus",
            params={"symbol": symbol},
            cache_ttl=TTL_ANALYST,
        ) or []
        estimates = self._get(
            "analyst-estimates",
            params={"symbol": symbol, "period": "quarter", "page": 0, "limit": limit},
            cache_ttl=TTL_ANALYST,
        ) or []

        consensus_row = _as_row(consensus)
        grades_row = _as_row(grades)
        estimate_rows = _as_rows(estimates)

        if not any([consensus_row, grades_row, estimate_rows]):
            return None

        strong_buy = _first_int(grades_row, "strongBuy", "strong_buy")
        buy = _first_int(grades_row, "buy")
        hold = _first_int(grades_row, "hold")
        sell = _first_int(grades_row, "sell")
        strong_sell = _first_int(grades_row, "strongSell", "strong_sell")

        buy_count = _sum_ints([strong_buy, buy])
        sell_count = _sum_ints([sell, strong_sell])
        analyst_count = _first_int(
            grades_row,
            "analystRatingsCount",
            "numberOfAnalystOpinions",
            "analystCount",
            "analyst_count",
        )
        if analyst_count is None:
            analyst_count = _sum_ints([buy_count, hold, sell_count])

        quarterly_estimates = [
            QuarterlyEstimate(
                period=_first_present(
                    row,
                    "period",
                    "fiscalPeriod",
                    "calendarYear",
                    default=f"Q{i + 1}",
                ),
                fiscal_date=_parse_date(
                    _first_present(row, "date", "fiscalDateEnding", "fiscalDate", default=None)
                ),
                eps_estimate=_first_num(
                    row,
                    "estimatedEpsAvg",
                    "estimatedEps",
                    "epsAvg",
                    "epsEstimated",
                ),
                revenue_estimate=_first_num(
                    row,
                    "estimatedRevenueAvg",
                    "estimatedRevenue",
                    "revenueAvg",
                    "revenueEstimated",
                ),
                analyst_count=_first_int(
                    row,
                    "numberAnalystEstimatedEps",
                    "numberAnalystEstimatedRevenue",
                    "analystCount",
                ),
            )
            for i, row in enumerate(estimate_rows[:limit])
        ]

        return AnalystForecastSnapshot(
            ticker=ticker,
            country=country,
            analyst_count=analyst_count,
            buy_count=buy_count,
            hold_count=hold,
            sell_count=sell_count,
            target_high=_first_num(consensus_row, "targetHigh", "highPriceTarget", "priceTargetHigh"),
            target_low=_first_num(consensus_row, "targetLow", "lowPriceTarget", "priceTargetLow"),
            target_avg=_first_num(
                consensus_row,
                "targetConsensus",
                "targetAverage",
                "priceTargetAverage",
                "targetMedian",
            ),
            current_price=_first_num(consensus_row, "currentPrice", "price") or current_price,
            consensus_rating=_first_present(
                grades_row,
                "consensus",
                "rating",
                "ratingRecommendation",
                default=None,
            ),
            quarterly_estimates=quarterly_estimates,
        )

    def get_stock_peers(
        self,
        ticker: str,
        country: Country,
        *,
        limit: int = 8,
    ) -> list[str]:
        symbol = _fmp_symbol(ticker, country)
        data = self._get(
            "stock-peers",
            params={"symbol": symbol},
            cache_ttl=TTL_PEERS,
        ) or []
        row = _as_row(data)
        if not row:
            return []

        peers: list[str] = []
        for key in ("peersList", "peers", "symbols", "peerSymbols"):
            value = row.get(key)
            if isinstance(value, list):
                peers.extend(str(item) for item in value if item)
            elif isinstance(value, str):
                peers.extend(part.strip() for part in value.split(",") if part.strip())

        if not peers and isinstance(data, list):
            for item in data:
                if isinstance(item, str):
                    peers.append(item)
                elif isinstance(item, dict):
                    peers.extend(
                        str(v)
                        for k, v in item.items()
                        if k.lower().startswith("peer") and isinstance(v, str)
                    )

        normalized: list[str] = []
        for peer in peers:
            clean = _normalize_vendor_ticker(peer)
            if clean and clean != ticker and clean not in normalized:
                normalized.append(clean)
        return normalized[:limit]

    def _to_news(
        self, row: dict[str, Any], ticker: str | None, country: Country | None
    ) -> NewsArticle | None:
        published = _parse_datetime(row.get("publishedDate") or row.get("date"))
        url = row.get("url") or row.get("link")
        headline = row.get("title") or row.get("headline")
        if not (published and url and headline):
            return None
        return NewsArticle(
            source=row.get("site") or row.get("source") or "fmp",
            headline=headline,
            url=url,
            published_at=published,
            summary=row.get("text") or row.get("description"),
            ticker=ticker,
            country=country,
        )

    # ------------------------------------------------------------------
    # Events — earnings calendar + dividend calendar
    # ------------------------------------------------------------------

    def get_upcoming_events(
        self, ticker: str, country: Country, within_days: int = 30
    ) -> list[EventRecord]:
        symbol = _fmp_symbol(ticker, country)
        today = date.today()
        horizon = today + timedelta(days=within_days)

        earnings = self._get("earnings", params={"symbol": symbol}, cache_ttl=TTL_EVENTS) or []
        dividends = self._get("dividends", params={"symbol": symbol}, cache_ttl=TTL_EVENTS) or []
        splits = self._get("splits", params={"symbol": symbol}, cache_ttl=TTL_EVENTS) or []

        events: list[EventRecord] = []
        for rec in earnings:
            d = _parse_date(rec.get("date"))
            if d and today <= d <= horizon:
                events.append(
                    EventRecord(
                        ticker=ticker,
                        country=country,
                        event_type=EventType.EARNINGS,
                        event_date=d,
                        meta={
                            "eps_estimate": rec.get("epsEstimated"),
                            "revenue_estimate": rec.get("revenueEstimated"),
                        },
                    )
                )

        div_list = dividends if isinstance(dividends, list) else (dividends.get("historical") or [])
        for rec in div_list:
            d = _parse_date(rec.get("date"))
            if d and today <= d <= horizon:
                events.append(
                    EventRecord(
                        ticker=ticker,
                        country=country,
                        event_type=EventType.EX_DIVIDEND,
                        event_date=d,
                        meta={"amount": rec.get("dividend") or rec.get("adjDividend")},
                    )
                )

        split_list = splits if isinstance(splits, list) else (splits.get("historical") or [])
        for rec in split_list:
            d = _parse_date(rec.get("date") or rec.get("executionDate"))
            if d and today <= d <= horizon:
                events.append(
                    EventRecord(
                        ticker=ticker,
                        country=country,
                        event_type=EventType.SPLIT,
                        event_date=d,
                        meta={"ratio": rec.get("numerator") or rec.get("splitRatio") or rec.get("label")},
                    )
                )
        return events



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _index_by_date(
    income: list[dict[str, Any]],
    balance: list[dict[str, Any]],
    cashflow: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Merge three statement lists into {fiscal_date_str: {income:…, balance:…, cashflow:…}}."""
    result: dict[str, dict[str, Any]] = {}
    _index_stmts(result, income, "income")
    _index_stmts(result, balance, "balance")
    _index_stmts(result, cashflow, "cashflow")
    return result


def _index_stmts(
    result: dict[str, dict[str, Any]],
    rows: list[dict[str, Any]],
    label: str,
) -> None:
    for row in rows:
        key = (str(row.get("date") or row.get("fillingDate") or ""))[:10]
        if key:
            result.setdefault(key, {})[label] = row


def _pick2(d1: dict[str, Any], k1: str, d2: dict[str, Any], k2: str) -> Any:
    """Return d1[k1] if truthy, else d2[k2]."""
    v = d1.get(k1)
    return v if (v is not None and v != "") else d2.get(k2)


def _extract_balance(
    bal: dict[str, Any],
) -> tuple[float | None, float | None, float | None]:
    """(total_debt, total_equity, debt_equity)"""
    debt = _num(bal.get("totalDebt") or bal.get("shortTermDebt"))
    equity = _num(bal.get("totalStockholdersEquity") or bal.get("totalEquity"))
    if debt is not None and equity and equity != 0:
        return debt, equity, debt / equity
    return debt, equity, None


def _extract_cf(
    cf: dict[str, Any],
) -> tuple[float | None, float | None]:
    """(operating_cash_flow, free_cash_flow)"""
    op = _num(cf.get("operatingCashFlow") or cf.get("netCashProvidedByOperatingActivities"))
    cap = _num(cf.get("capitalExpenditure") or cf.get("investmentsInPropertyPlantAndEquipment"))
    if op is not None and cap is not None:
        return op, op - abs(cap)
    return op, None


def _ratio_kwargs(
    inc: dict[str, Any],
    ratios: dict[str, Any],
    km: dict[str, Any],
) -> dict[str, float | None]:
    """Build the ratio/margin/valuation kwargs for FundamentalSnapshot."""
    return {
        "roe": _num(_pick2(ratios, "returnOnEquityTTM", km, "roe")),
        "roce": _num(_pick2(ratios, "returnOnCapitalEmployedTTM", km, "roic")),
        "gross_margin": _num(_pick2(ratios, "grossProfitMarginTTM", inc, "grossProfitRatio")),
        "operating_margin": _num(_pick2(ratios, "operatingProfitMarginTTM", inc, "operatingIncomeRatio")),
        "net_margin": _num(_pick2(ratios, "netProfitMarginTTM", inc, "netIncomeRatio")),
        "pe": _num(_pick2(ratios, "peRatioTTM", km, "peRatio")),
        "peg": _num(_pick2(ratios, "pegRatioTTM", km, "pegRatio")),
        "pb": _num(_pick2(ratios, "priceToBookRatioTTM", km, "pbRatio")),
        "ev_ebitda": _num(_pick2(ratios, "enterpriseValueMultipleTTM", km, "evToEbitda")),
        "dividend_per_share": _num(_pick2(ratios, "dividendPerShareTTM", km, "dividendPerShare")),
        "dividend_yield": _num(_pick2(ratios, "dividendYieldTTM", km, "dividendYield")),
        "payout_ratio": _num(ratios.get("payoutRatioTTM")),
    }


def _build_snapshot(
    ticker: str,
    country: Country,
    index: int,
    fiscal_str: str,
    parts: dict[str, Any],
    ttm_ratios: dict[str, Any],
    ttm_km: dict[str, Any],
) -> FundamentalSnapshot | None:
    """Assemble a FundamentalSnapshot from merged statement parts + TTM dicts."""
    fiscal_date = _parse_date(fiscal_str)
    if fiscal_date is None:
        return None

    inc: dict[str, Any] = parts.get("income", {})
    bal: dict[str, Any] = parts.get("balance", {})
    cf: dict[str, Any] = parts.get("cashflow", {})

    # TTM ratios/metrics only used for the most-recent quarter
    ratios = ttm_ratios if index == 0 else {}
    km = ttm_km if index == 0 else {}

    total_debt, total_equity, debt_equity = _extract_balance(bal)
    op_cf, free_cf = _extract_cf(cf)
    period_label = f"{fiscal_date.year}Q{(fiscal_date.month - 1) // 3 + 1}"

    return FundamentalSnapshot(
        ticker=ticker,
        country=country,
        fiscal_date=fiscal_date,
        period=period_label,
        revenue=_num(inc.get("revenue") or inc.get("totalRevenue")),
        net_income=_num(inc.get("netIncome")),
        eps=_num(inc.get("eps") or inc.get("epsdiluted")),
        total_debt=total_debt,
        total_equity=total_equity,
        debt_equity=debt_equity,
        operating_cash_flow=op_cf,
        free_cash_flow=free_cf,
        **_ratio_kwargs(inc, ratios, km),
    )


def _num(val: Any) -> float | None:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _first_present(row: dict[str, Any] | None, *keys: str, default: Any = None) -> Any:
    if not row:
        return default
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return default


def _first_num(row: dict[str, Any] | None, *keys: str) -> float | None:
    return _num(_first_present(row, *keys))


def _first_int(row: dict[str, Any] | None, *keys: str) -> int | None:
    value = _first_present(row, *keys)
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _sum_ints(values: list[int | None]) -> int | None:
    nums = [value for value in values if value is not None]
    return sum(nums) if nums else None


def _as_row(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        return data
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    return {}


def _as_rows(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        for key in ("data", "items", "results"):
            value = data.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
        return [data]
    return []


def _normalize_vendor_ticker(ticker: str | None) -> str | None:
    if not ticker:
        return None
    clean = str(ticker).strip().upper()
    for suffix in (".NS", ".BO"):
        if clean.endswith(suffix):
            return clean[: -len(suffix)]
    return clean


def _parse_date(val: Any) -> date | None:
    if not val:
        return None
    if isinstance(val, date):
        return val
    try:
        return datetime.strptime(str(val)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_datetime(val: Any) -> datetime | None:
    if not val:
        return None
    if isinstance(val, datetime):
        return val
    s = str(val).strip().replace("T", " ").rstrip("Z").split(".")[0]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


# Silence unused-import lint
_ = NewsStream
