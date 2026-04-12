"""VADER-based headline sentiment scorer (F-13.1.4).

Each news item is scored positive / neutral / negative and gets a compound score
in the range [-1, 1]. Thresholds follow the VADER paper recommendations:
  compound >= +0.05  → positive
  compound <= -0.05  → negative
  else               → neutral
"""
from __future__ import annotations

from dataclasses import dataclass

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from pipeline.db.enums import SentimentLabel

_analyzer: SentimentIntensityAnalyzer | None = None


def _get_analyzer() -> SentimentIntensityAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = SentimentIntensityAnalyzer()
    return _analyzer


@dataclass
class SentimentResult:
    """Output of scoring a single headline."""

    text: str
    compound: float       # [-1, 1] — the main signal
    positive: float       # fraction of text that is positive
    neutral: float        # fraction of text that is neutral
    negative: float       # fraction of text that is negative
    label: SentimentLabel


class SentimentScorer:
    """Thin wrapper around VADER for headline sentiment analysis."""

    # VADER paper thresholds
    POSITIVE_THRESHOLD = 0.05
    NEGATIVE_THRESHOLD = -0.05

    def score(self, text: str) -> SentimentResult:
        """Score a single headline or short text."""
        analyzer = _get_analyzer()
        scores = analyzer.polarity_scores(text)
        compound = scores["compound"]
        if compound >= self.POSITIVE_THRESHOLD:
            label = SentimentLabel.POSITIVE
        elif compound <= self.NEGATIVE_THRESHOLD:
            label = SentimentLabel.NEGATIVE
        else:
            label = SentimentLabel.NEUTRAL

        return SentimentResult(
            text=text,
            compound=compound,
            positive=scores["pos"],
            neutral=scores["neu"],
            negative=scores["neg"],
            label=label,
        )

    def score_many(self, texts: list[str]) -> list[SentimentResult]:
        """Score a list of headlines in order."""
        return [self.score(t) for t in texts]
