"""String enums used across DB and scoring layer. Kept as StrEnum so they
serialize cleanly to SQLite TEXT columns without custom type handlers."""
from __future__ import annotations

from enum import StrEnum


class Country(StrEnum):
    INDIA = "IN"
    US = "US"


class Bucket(StrEnum):
    QUALITY_VALUE = "quality_value"
    MOMENTUM = "momentum"
    QUALITY_MOMENTUM = "quality_momentum"
    DIVIDEND_GROWTH = "dividend_growth"


class IndexName(StrEnum):
    NIFTY_50 = "NIFTY_50"
    NIFTY_500 = "NIFTY_500"
    SP_100 = "SP_100"
    SP_500 = "SP_500"


class NewsStream(StrEnum):
    STOCK = "stock"
    GENERAL = "general"


class NewsCategory(StrEnum):
    EARNINGS = "earnings"
    MANAGEMENT = "management"
    REGULATORY = "regulatory"
    M_AND_A = "m_and_a"
    DIVIDEND = "dividend"
    OTHER = "other"


class SentimentLabel(StrEnum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class EventType(StrEnum):
    EARNINGS = "earnings"
    EX_DIVIDEND = "ex_dividend"
    SPLIT = "split"
    CORPORATE_ACTION = "corporate_action"


class MacroRegime(StrEnum):
    RISK_ON = "risk_on"
    CAUTION = "caution"
    RISK_OFF = "risk_off"


class ShockBanner(StrEnum):
    RED = "red"
    YELLOW = "yellow"


class ActionType(StrEnum):
    BUY = "buy"
    SELL = "sell"
    ADD = "add"
    TRIM = "trim"
    HOLD = "hold"
    SKIP_MONTH = "skip_month"


class Broker(StrEnum):
    KITE = "kite"
    VESTED = "vested"
    HDFC = "hdfc"
    OTHER = "other"
