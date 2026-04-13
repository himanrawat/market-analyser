"""Helpers for presenting event metadata in API responses."""
from __future__ import annotations

from typing import Any


def format_event_description(meta: Any) -> str | None:
    """Return a human-readable event description from stored event metadata."""
    if not isinstance(meta, dict):
        text = str(meta).strip() if meta is not None else ""
        return text or None

    for key in ("headline", "description", "purpose", "subject", "title", "bm_desc", "bm_purpose"):
        value = _clean_text(meta.get(key))
        if value:
            return value

    raw = meta.get("raw")
    if isinstance(raw, dict):
        for key in ("headline", "description", "purpose", "subject", "title", "bm_desc", "bm_purpose"):
            value = _clean_text(raw.get(key))
            if value:
                return value

    amount = _clean_text(meta.get("amount"))
    if amount:
        return f"Amount: {amount}"

    ratio = _clean_text(meta.get("ratio"))
    if ratio:
        return f"Ratio: {ratio}"

    eps_estimate = _clean_text(meta.get("eps_estimate"))
    revenue_estimate = _clean_text(meta.get("revenue_estimate"))
    parts = []
    if eps_estimate:
        parts.append(f"EPS est: {eps_estimate}")
    if revenue_estimate:
        parts.append(f"Revenue est: {revenue_estimate}")
    if parts:
        return " · ".join(parts)

    return None


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
