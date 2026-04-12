"""File-based JSON cache for provider responses.

F-1.7 and F-12.3 require that the pipeline never re-fetches data already
present and fresh. The SQLite database is the *primary* cache (scoring reads
from it). This file cache sits one layer lower: it de-duplicates HTTP calls
*within* a single pipeline run and across quick re-runs during development.

Design notes:
- Keyed by (provider, endpoint, args) → stable hash
- Stored as JSON files under data_dir/cache/<provider>/<hash>.json
- TTL enforced per-call; expired entries are still on disk (for audit) but
  `get()` returns None
- No LRU eviction in v1 — a single rebalance run fits easily on disk
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger

from pipeline.config import settings


class JsonCache:
    """Thin file-based cache. One instance per provider, by convention."""

    def __init__(self, provider: str, root: Path | None = None) -> None:
        self.provider = provider
        self.root = (root or settings.data_dir) / "cache" / provider
        self.root.mkdir(parents=True, exist_ok=True)

    def _key(self, endpoint: str, args: dict[str, Any]) -> Path:
        serialized = json.dumps({"endpoint": endpoint, "args": args}, sort_keys=True, default=str)
        digest = hashlib.sha1(serialized.encode()).hexdigest()
        return self.root / f"{digest}.json"

    def get(self, endpoint: str, args: dict[str, Any], ttl: timedelta) -> Any | None:
        path = self._key(endpoint, args)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(f"Cache read failed for {path.name}: {exc}")
            return None

        cached_at = datetime.fromisoformat(payload["cached_at"])
        if datetime.utcnow() - cached_at > ttl:
            return None
        return payload["data"]

    def set(self, endpoint: str, args: dict[str, Any], data: Any) -> None:
        path = self._key(endpoint, args)
        payload = {
            "provider": self.provider,
            "endpoint": endpoint,
            "args": args,
            "cached_at": datetime.utcnow().isoformat(),
            "data": data,
        }
        try:
            path.write_text(json.dumps(payload, default=str))
        except OSError as exc:
            logger.warning(f"Cache write failed for {path.name}: {exc}")

    def clear(self) -> int:
        count = 0
        for f in self.root.glob("*.json"):
            f.unlink()
            count += 1
        return count
