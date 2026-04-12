"""Tests for Telegram notifier."""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from pipeline.db.enums import ActionType, Bucket, Country, ShockBanner
from pipeline.db.models import ShockEvent
from pipeline.notify.telegram import TelegramNotifier, _format_digest, _format_shock_alert
from pipeline.portfolio.diff import ActionRow, DiffResult


def _make_action(ticker, action, bucket=Bucket.QUALITY_MOMENTUM, score=80.0, rank=1):
    return ActionRow(
        ticker=ticker,
        country=Country.US,
        bucket=bucket,
        action=action,
        score=score,
        rank=rank,
        reason="test",
    )


def _make_result(actions, macro_regime="risk_on", shock=False):
    return DiffResult(
        run_date=date(2026, 4, 7),
        actions=actions,
        macro_regime=macro_regime,
        shock_regime=shock,
    )


def _make_shock_event(banner=ShockBanner.RED):
    event = MagicMock(spec=ShockEvent)
    event.banner = banner
    event.triggered_at = datetime(2026, 4, 7, 10, 30, tzinfo=timezone.utc)
    event.headline = "Military invasion begins in Eastern Europe"
    event.source = "Reuters"
    event.matched_keywords = ["military invasion", "invasion"]
    event.india_vix_change_pct = 25.0
    event.us_vix_change_pct = 30.0
    return event


class TestTelegramNotifier:
    def test_not_configured_returns_false(self):
        notifier = TelegramNotifier(bot_token="", chat_id="")
        result = notifier.send_text("hello")
        assert result is False

    def test_send_text_calls_post(self):
        notifier = TelegramNotifier(bot_token="tok123", chat_id="chat456")
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        with patch("pipeline.notify.telegram.requests.post", return_value=mock_resp) as mock_post:
            result = notifier.send_text("hello world")
        assert result is True
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert "tok123" in call_kwargs.args[0]

    def test_send_monthly_digest_sends_message(self):
        notifier = TelegramNotifier(bot_token="tok", chat_id="cid")
        result_obj = _make_result([
            _make_action("AAPL", ActionType.BUY),
            _make_action("MSFT", ActionType.SELL),
        ])
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        with patch("pipeline.notify.telegram.requests.post", return_value=mock_resp):
            sent = notifier.send_monthly_digest(result_obj)
        assert sent is True

    def test_send_shock_alert_sends_message(self):
        notifier = TelegramNotifier(bot_token="tok", chat_id="cid")
        event = _make_shock_event(ShockBanner.RED)
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        with patch("pipeline.notify.telegram.requests.post", return_value=mock_resp):
            sent = notifier.send_shock_alert(event)
        assert sent is True

    def test_request_exception_returns_false(self):
        import requests as req_lib
        notifier = TelegramNotifier(bot_token="tok", chat_id="cid")
        with patch("pipeline.notify.telegram.requests.post",
                   side_effect=req_lib.RequestException("timeout")):
            result = notifier.send_text("hi")
        assert result is False

    def test_message_truncated_at_4096(self):
        notifier = TelegramNotifier(bot_token="tok", chat_id="cid")
        long_text = "x" * 10000
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        with patch("pipeline.notify.telegram.requests.post", return_value=mock_resp) as mock_post:
            notifier.send_text(long_text)
        sent_payload = mock_post.call_args.kwargs["json"]
        assert len(sent_payload["text"]) <= 4096


class TestFormatDigest:
    def test_includes_run_date(self):
        result = _make_result([])
        text = _format_digest(result)
        assert "07 Apr 2026" in text

    def test_includes_buy_tickers(self):
        result = _make_result([_make_action("AAPL", ActionType.BUY)])
        text = _format_digest(result)
        assert "AAPL" in text
        assert "BUY" in text

    def test_includes_sell_tickers(self):
        result = _make_result([_make_action("MSFT", ActionType.SELL, rank=None)])
        text = _format_digest(result)
        assert "MSFT" in text
        assert "SELL" in text

    def test_shock_regime_warning_shown(self):
        result = _make_result([], shock=True)
        text = _format_digest(result)
        assert "SHOCK REGIME" in text

    def test_no_shock_no_warning(self):
        result = _make_result([], shock=False)
        text = _format_digest(result)
        assert "SHOCK REGIME" not in text

    def test_risk_off_macro_shown(self):
        result = _make_result([], macro_regime="risk_off")
        text = _format_digest(result)
        assert "Risk Off" in text or "risk_off" in text.lower()


class TestFormatShockAlert:
    def test_red_banner_shows_alert(self):
        event = _make_shock_event(ShockBanner.RED)
        text = _format_shock_alert(event)
        assert "RED ALERT" in text
        assert "🚨" in text

    def test_yellow_banner_shows_caution(self):
        event = _make_shock_event(ShockBanner.YELLOW)
        text = _format_shock_alert(event)
        assert "YELLOW CAUTION" in text
        assert "⚠️" in text

    def test_headline_included(self):
        event = _make_shock_event()
        text = _format_shock_alert(event)
        assert "Military invasion" in text

    def test_red_banner_rule_shown(self):
        event = _make_shock_event(ShockBanner.RED)
        text = _format_shock_alert(event)
        assert "pause new buys" in text.lower()

    def test_vix_spike_shown(self):
        event = _make_shock_event()
        text = _format_shock_alert(event)
        assert "25.0%" in text or "India VIX" in text
