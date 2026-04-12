"""News processing: VADER sentiment scoring + two-signal market-shock detector."""
from pipeline.news.sentiment import SentimentScorer, SentimentResult
from pipeline.news.shock import ShockDetector, ShockSignal, SHOCK_KEYWORDS

__all__ = [
    "SentimentScorer",
    "SentimentResult",
    "ShockDetector",
    "ShockSignal",
    "SHOCK_KEYWORDS",
]
