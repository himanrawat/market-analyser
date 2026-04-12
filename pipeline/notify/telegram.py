"""Telegram notifier: monthly digest + RED-banner shock alerts (F-11.4).

Sends messages via the Telegram Bot API using a plain HTTP POST so there is
no heavyweight dependency — just `requests` (already a project dep).

The notifier is intentionally stateless: callers build the message text and
pass it in; this class only handles delivery and error handling.

Configuration (from .env):
  TELEGRAM_BOT_TOKEN — Bot token from @BotFather
  TELEGRAM_CHAT_ID   — Your personal chat / channel ID

If either value is missing the notifier is a no-op (logs a warning instead
of raising) so the pipeline can run in environments without Telegram set up.
"""
from __future__ import annotations

import requests
from loguru import logger

from pipeline.config import settings
from pipeline.db.enums import ActionType, ShockBanner
from pipeline.db.models import ShockEvent
from pipeline.portfolio.diff import ActionRow, DiffResult

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

# Max message length Telegram allows in one sendMessage call
_MAX_LEN = 4096


class TelegramNotifier:
    """Sends pipeline output to a Telegram chat."""

    def __init__(
        self,
        bot_token: str | None = None,
        chat_id: str | None = None,
    ) -> None:
        self._token = settings.telegram_bot_token if bot_token is None else bot_token
        self._chat_id = settings.telegram_chat_id if chat_id is None else chat_id

    @property
    def _configured(self) -> bool:
        return bool(self._token and self._chat_id)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_monthly_digest(self, result: DiffResult) -> bool:
        """Format and send the monthly rebalance digest.

        Returns True if the message was sent, False if skipped or failed.
        """
        text = _format_digest(result)
        return self._send(text)

    def send_shock_alert(self, event: ShockEvent) -> bool:
        """Send a RED/YELLOW banner shock alert immediately.

        Returns True if sent, False if skipped or failed.
        """
        text = _format_shock_alert(event)
        return self._send(text)

    def send_text(self, text: str) -> bool:
        """Send arbitrary text — useful for heartbeat / error messages."""
        return self._send(text)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _send(self, text: str) -> bool:
        if not self._configured:
            logger.warning(
                "Telegram not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing). "
                "Skipping notification."
            )
            return False

        url = _TELEGRAM_API.format(token=self._token)
        # Telegram silently truncates at MAX_LEN; we truncate ourselves to be explicit.
        payload = {
            "chat_id": self._chat_id,
            "text": text[:_MAX_LEN],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        try:
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            logger.info("Telegram message sent (chat_id={})", self._chat_id)
            return True
        except requests.RequestException as exc:
            logger.error("Failed to send Telegram message: {}", exc)
            return False


# ---------------------------------------------------------------------------
# Message formatters
# ---------------------------------------------------------------------------

def _format_digest(result: DiffResult) -> str:
    """Build the monthly rebalance digest text (HTML-formatted)."""
    buys = result.buys
    sells = result.sells
    adds = result.adds
    holds = result.holds

    regime_emoji = "🟢" if "risk_on" in result.macro_regime.lower() else (
        "🔴" if "risk_off" in result.macro_regime.lower() else "🟡"
    )
    shock_note = "\n⚠️ <b>SHOCK REGIME — review carefully before deploying capital.</b>" if result.shock_regime else ""

    lines = [
        f"📊 <b>Monthly Rebalance — {result.run_date.strftime('%d %b %Y')}</b>",
        f"{regime_emoji} Macro: {result.macro_regime.replace('_', ' ').title()}",
        shock_note,
        "",
    ]

    if buys:
        lines.append(f"<b>BUY ({len(buys)})</b>")
        for a in buys:
            lines.append(f"  • {a.ticker} — score {a.score:.1f}, rank #{a.rank}")
        lines.append("")

    if adds:
        lines.append(f"<b>ADD ({len(adds)})</b>")
        for a in adds:
            lines.append(f"  • {a.ticker} — underweight, score {a.score:.1f}")
        lines.append("")

    if sells:
        lines.append(f"<b>SELL ({len(sells)})</b>")
        for a in sells:
            lines.append(f"  • {a.ticker} — {a.reason}")
        lines.append("")

    if holds:
        lines.append(f"<b>HOLD ({len(holds)})</b>: " + ", ".join(a.ticker for a in holds))
        lines.append("")

    lines.append("Open the app to review full action table and execute trades.")
    return "\n".join(l for l in lines if l is not None)


def _format_shock_alert(event: ShockEvent) -> str:
    """Build the shock alert text for immediate push."""
    banner = ShockBanner(event.banner)
    emoji = "🚨" if banner == ShockBanner.RED else "⚠️"
    color = "RED ALERT" if banner == ShockBanner.RED else "YELLOW CAUTION"

    lines = [
        f"{emoji} <b>MARKET SHOCK — {color}</b>",
        f"<i>{event.triggered_at.strftime('%d %b %Y %H:%M UTC')}</i>",
        "",
        f"📰 {event.headline}",
        f"Source: {event.source}",
        "",
    ]

    if event.matched_keywords:
        lines.append(f"Keywords matched: {', '.join(event.matched_keywords[:5])}")

    vix_parts = []
    if event.india_vix_change_pct is not None:
        vix_parts.append(f"India VIX +{event.india_vix_change_pct:.1f}%")
    if event.us_vix_change_pct is not None:
        vix_parts.append(f"US VIX +{event.us_vix_change_pct:.1f}%")
    if vix_parts:
        lines.append(f"VIX spike: {', '.join(vix_parts)}")

    lines.append("")

    if banner == ShockBanner.RED:
        lines.append(
            "🔴 <b>Red banner = pause new buys for the rest of the month. "
            "Red banner ≠ sell what you already own.</b>"
        )
    else:
        lines.append("🟡 Potential developing situation — monitor closely.")

    return "\n".join(lines)
