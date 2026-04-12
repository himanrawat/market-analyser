"""NewsAPI.org backup provider for general market news (shock detection).

F-13.2.1: polled every 30 min from global headlines, this is the backup
when FMP general news is unavailable. The free dev tier has a 24h delay,
which is acceptable for shock detection (F-13.2.7).

Docs: https://newsapi.org/docs/endpoints/everything
"""
from __future__ import annotations

from datetime import datetime, timedelta

from loguru import logger

from pipeline.config import settings
from pipeline.providers._http import get_json
from pipeline.providers.cache import JsonCache
from pipeline.providers.dto import NewsArticle
from pipeline.providers.errors import MissingApiKeyError

PROVIDER_NAME = "newsapi"
BASE_URL = "https://newsapi.org/v2"
TTL = timedelta(minutes=30)

# Financial/market keywords to filter for relevance
FINANCIAL_QUERY = (
    "stock market OR inflation OR interest rate OR recession OR "
    "Federal Reserve OR RBI OR Nifty OR S&P 500 OR economy OR GDP"
)


class NewsAPIProvider:
    def __init__(self, cache: JsonCache | None = None) -> None:
        self.cache = cache or JsonCache(PROVIDER_NAME)

    def _require_key(self) -> str:
        key = settings.newsapi_key
        if not key:
            raise MissingApiKeyError(PROVIDER_NAME, "NEWSAPI_KEY")
        return key

    def get_general_news(self, since: datetime, limit: int = 100) -> list[NewsArticle]:
        key = self._require_key()
        cache_args = {"since": since.isoformat()[:13], "limit": limit}  # hour-level key
        cached = self.cache.get("everything", cache_args, TTL)
        if cached is not None:
            logger.debug("[newsapi] cache hit: general news")
            return [NewsArticle(**a) for a in cached]

        params = {
            "q": FINANCIAL_QUERY,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": min(limit, 100),
            "from": since.strftime("%Y-%m-%dT%H:%M:%S"),
            "apiKey": key,
        }
        data = get_json(f"{BASE_URL}/everything", params=params)
        articles_raw = data.get("articles") or []

        articles: list[NewsArticle] = []
        for row in articles_raw:
            pub = _parse_dt(row.get("publishedAt"))
            url = row.get("url")
            headline = row.get("title")
            if not (pub and url and headline):
                continue
            articles.append(
                NewsArticle(
                    source=row.get("source", {}).get("name") or "newsapi",
                    headline=headline,
                    url=url,
                    published_at=pub,
                    summary=row.get("description"),
                )
            )

        self.cache.set("everything", cache_args, [a.model_dump() for a in articles])
        logger.debug(f"[newsapi] fetched {len(articles)} general articles")
        return articles


def _parse_dt(val: str | None) -> datetime | None:
    if not val:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(val[:19], fmt[:len(val)])
        except ValueError:
            continue
    return None
