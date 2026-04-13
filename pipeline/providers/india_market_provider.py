"""Official India runtime provider for quotes, profile metadata, news, events,
bulk/block deals, insider trades, market depth, derivatives, and market breadth.

Priority order for every data type:
  1. NSE official endpoints
  2. BSE official endpoints (using bse_scripcode from stock master)
  3. Yahoo Finance fallback (quotes and profile only)

FMP is not used anywhere in this provider.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
from loguru import logger

from pipeline.db.enums import Country, EventType
from pipeline.importers.india_official import BSEOfficialClient, NSEOfficialClient
from pipeline.providers.dto import (
    BulkDealRecord,
    DerivativesSentiment,
    EventRecord,
    InsiderTradeRecord,
    MarketBreadthSnapshot,
    MarketDepthLevel,
    MarketDepthSnapshot,
    NewsArticle,
    PriceBar,
    StockProfile,
)
from pipeline.providers.errors import SymbolNotFoundError
from pipeline.providers.yfinance_provider import YFinanceProvider

PROVIDER_NAME = "india_market"
_NSE_BASE = "https://www.nseindia.com"
_ANNOUNCEMENTS_PAGE = (
    "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
)

# NSE index symbol → model field mapping for breadth snapshot
_INDEX_FIELD_MAP: dict[str, str] = {
    "NIFTY 50": "nifty_50",
    "NIFTY50": "nifty_50",
    "S&P BSE SENSEX": "sensex",
    "SENSEX": "sensex",
    "NIFTY BANK": "nifty_bank",
    "NIFTY IT": "nifty_it",
    "NIFTY FMCG": "nifty_fmcg",
    "NIFTY AUTO": "nifty_auto",
    "NIFTY PHARMA": "nifty_pharma",
    "NIFTY REALTY": "nifty_realty",
    "NIFTY METAL": "nifty_metal",
    "NIFTY ENERGY": "nifty_energy",
}


class IndiaMarketProvider:
    """Official-first runtime provider for all India stock surfaces."""

    def __init__(
        self,
        *,
        client: NSEOfficialClient | None = None,
        bse_client: BSEOfficialClient | None = None,
        yf: YFinanceProvider | None = None,
    ) -> None:
        self._nse = client or NSEOfficialClient()
        self._bse = bse_client or BSEOfficialClient()
        self._yf = yf or YFinanceProvider()

    # ------------------------------------------------------------------
    # Latest quote  (NSE → BSE → Yahoo)
    # ------------------------------------------------------------------

    def get_latest_quote(self, ticker: str, country: Country) -> PriceBar:
        symbol = _normalize_symbol(ticker, country)

        # NSE first
        try:
            payload = self._nse.get_quote_equity(symbol)
            bar = _quote_to_price_bar(payload, symbol, country)
            if bar is not None:
                return bar
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"NSE quote unavailable for {symbol}: {exc}")

        # BSE fallback (requires scripcode)
        scripcode = self._scripcode_for(symbol)
        if scripcode:
            try:
                bse_quote = self._bse.get_stock_quote(scripcode)
                bar = _bse_quote_to_price_bar(bse_quote, symbol, country)
                if bar is not None:
                    return bar
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"BSE quote unavailable for {symbol} (scripcode={scripcode}): {exc}")

        return self._yf.get_latest_quote(symbol, country)

    # ------------------------------------------------------------------
    # Profile  (NSE → Yahoo)
    # ------------------------------------------------------------------

    def get_profile(self, ticker: str, country: Country) -> StockProfile:
        symbol = _normalize_symbol(ticker, country)
        fallback = self._safe_yf_profile(symbol, country)

        try:
            meta = self._nse.get_equity_meta(symbol)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Official India profile unavailable for {symbol}: {exc}")
            if fallback is not None:
                return fallback
            raise SymbolNotFoundError(symbol, PROVIDER_NAME) from exc

        quote: dict[str, Any] = {}
        try:
            quote = self._nse.get_quote_equity(symbol)
        except Exception:  # noqa: BLE001
            pass

        return StockProfile(
            ticker=symbol,
            country=country,
            name=_first_text(meta, "companyName", "company_name") or (fallback.name if fallback else symbol),
            sector=(fallback.sector if fallback else None),
            industry=_first_text(meta, "industry", "industryInfo") or (fallback.industry if fallback else None),
            currency="INR",
            market_cap=_market_cap_from_quote(quote) or (fallback.market_cap if fallback else None),
            listing_date=fallback.listing_date if fallback else None,
            description=fallback.description if fallback else None,
            isin=_first_text(meta, "isin", "isinCode") or (fallback.isin if fallback else None),
            nse_symbol=_first_text(meta, "symbol", "symbolName", default=symbol),
            bse_symbol=_first_text(meta, "bseSymbol", "bse_symbol") or (fallback.bse_symbol if fallback else None),
            bse_scripcode=_first_text(meta, "bseScriptCode", "bseScripCode", "scripCode")
            or (fallback.bse_scripcode if fallback else None),
        )

    # ------------------------------------------------------------------
    # Stock news (NSE announcements → empty)
    # ------------------------------------------------------------------

    def get_stock_news(
        self,
        ticker: str,
        country: Country,
        since: datetime,
        limit: int = 50,
    ) -> list[NewsArticle]:
        symbol = _normalize_symbol(ticker, country)
        try:
            rows = self._nse.get_corporate_announcements(symbol)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"NSE announcements unavailable for {symbol}: {exc}")
            rows = []

        # BSE fallback if NSE returned nothing
        if not rows:
            scripcode = self._scripcode_for(symbol)
            if scripcode:
                try:
                    bse_rows = self._bse.get_corporate_announcements(scripcode)
                    rows = bse_rows
                except Exception as exc:  # noqa: BLE001
                    logger.debug(f"BSE announcements unavailable for {symbol}: {exc}")

        articles: list[NewsArticle] = []
        seen_urls: set[str] = set()
        for row in rows:
            published_at = _parse_datetime(
                _first_text(row, "an_dt", "broadcastDateTime", "broadcastDate", "dateTime", "date", "Newsdatetime")
            )
            if published_at is None or published_at < since:
                continue
            url = _announcement_url(row, symbol)
            if url in seen_urls:
                continue
            headline = (
                _first_text(row, "subject", "headline", "desc", "description", "Newssub")
                or f"{symbol} corporate announcement"
            )
            articles.append(
                NewsArticle(
                    source=_first_text(row, "exchange", "source", default="NSE"),
                    headline=headline,
                    summary=_first_text(row, "description", "details", "desc"),
                    url=url,
                    published_at=published_at,
                    ticker=symbol,
                    country=country,
                )
            )
            seen_urls.add(url)

        articles.sort(key=lambda a: a.published_at, reverse=True)
        return articles[:limit]

    # ------------------------------------------------------------------
    # Events (NSE board meetings + corporate actions → BSE fallback)
    # ------------------------------------------------------------------

    def get_upcoming_events(
        self,
        ticker: str,
        country: Country,
        within_days: int = 30,
    ) -> list[EventRecord]:
        symbol = _normalize_symbol(ticker, country)
        start = date.today()
        horizon = start + timedelta(days=within_days)
        scripcode = self._scripcode_for(symbol)

        events: list[EventRecord] = []
        events.extend(self._board_meeting_events(symbol, country, scripcode, start, horizon))
        events.extend(self._corporate_action_events(symbol, country, scripcode, start, horizon))

        deduped: dict[tuple[EventType, date, str], EventRecord] = {}
        for event in events:
            note = str(event.meta.get("headline") or event.meta.get("purpose") or "")
            deduped[(event.event_type, event.event_date, note)] = event

        return sorted(deduped.values(), key=lambda e: e.event_date)

    # ------------------------------------------------------------------
    # Bulk and block deals (NSE → BSE fallback)
    # ------------------------------------------------------------------

    def get_bulk_deals(
        self, ticker: str, country: Country, limit: int = 100
    ) -> list[BulkDealRecord]:
        symbol = _normalize_symbol(ticker, country)
        records: list[BulkDealRecord] = []

        try:
            rows = self._nse.get_bulk_deals(symbol)
            for row in rows:
                rec = _nse_deal_to_record(row, symbol, country, "bulk")
                if rec:
                    records.append(rec)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"NSE bulk deals unavailable for {symbol}: {exc}")

        try:
            rows = self._nse.get_block_deals(symbol)
            for row in rows:
                rec = _nse_deal_to_record(row, symbol, country, "block")
                if rec:
                    records.append(rec)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"NSE block deals unavailable for {symbol}: {exc}")

        # BSE fallback if NSE returned nothing
        if not records:
            scripcode = self._scripcode_for(symbol)
            if scripcode:
                try:
                    for row in self._bse.get_bulk_deals(scripcode):
                        rec = _bse_deal_to_record(row, symbol, country, "bulk")
                        if rec:
                            records.append(rec)
                    for row in self._bse.get_block_deals(scripcode):
                        rec = _bse_deal_to_record(row, symbol, country, "block")
                        if rec:
                            records.append(rec)
                except Exception as exc:  # noqa: BLE001
                    logger.debug(f"BSE deals unavailable for {symbol}: {exc}")

        records.sort(key=lambda r: r.trade_date, reverse=True)
        return records[:limit]

    # ------------------------------------------------------------------
    # Insider trades (NSE → BSE fallback)
    # ------------------------------------------------------------------

    def get_insider_trades(
        self, ticker: str, country: Country, limit: int = 100
    ) -> list[InsiderTradeRecord]:
        symbol = _normalize_symbol(ticker, country)
        records: list[InsiderTradeRecord] = []

        try:
            rows = self._nse.get_insider_trades(symbol)
            for row in rows:
                rec = _nse_insider_to_record(row, symbol, country)
                if rec:
                    records.append(rec)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"NSE insider trades unavailable for {symbol}: {exc}")

        if not records:
            scripcode = self._scripcode_for(symbol)
            if scripcode:
                try:
                    for row in self._bse.get_insider_trades(scripcode):
                        rec = _bse_insider_to_record(row, symbol, country)
                        if rec:
                            records.append(rec)
                except Exception as exc:  # noqa: BLE001
                    logger.debug(f"BSE insider trades unavailable for {symbol}: {exc}")

        records.sort(
            key=lambda r: (r.trade_date or r.to_date or date.min),
            reverse=True,
        )
        return records[:limit]

    # ------------------------------------------------------------------
    # Market depth (NSE → BSE fallback → empty)
    # ------------------------------------------------------------------

    def get_market_depth(self, ticker: str, country: Country) -> MarketDepthSnapshot | None:
        symbol = _normalize_symbol(ticker, country)

        try:
            raw_depth = self._nse.get_market_depth(symbol)
            snap = _nse_depth_to_snapshot(raw_depth, symbol, country)
            if snap is not None:
                return snap
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"NSE market depth unavailable for {symbol}: {exc}")

        # BSE depth fallback: extract from price graph endpoint
        scripcode = self._scripcode_for(symbol)
        if scripcode:
            try:
                bse_graph = self._bse.get_price_graph(scripcode)
                snap = _bse_depth_from_graph(bse_graph, symbol, country)
                if snap is not None:
                    return snap
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"BSE market depth unavailable for {symbol}: {exc}")

        return None

    # ------------------------------------------------------------------
    # Derivatives / F&O sentiment (NSE only)
    # ------------------------------------------------------------------

    def get_derivatives_sentiment(
        self, ticker: str, country: Country
    ) -> DerivativesSentiment | None:
        symbol = _normalize_symbol(ticker, country)
        try:
            chain = self._nse.get_option_chain(symbol)
            return _option_chain_to_sentiment(chain, symbol, country)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"NSE option chain unavailable for {symbol}: {exc}")
            return None

    # ------------------------------------------------------------------
    # Market breadth and index context (NSE)
    # ------------------------------------------------------------------

    def get_market_breadth(self) -> MarketBreadthSnapshot | None:
        today = date.today()
        breadth: dict[str, Any] = {}

        try:
            adv_dec = self._nse.get_advance_decline()
            if isinstance(adv_dec, dict):
                breadth.update(adv_dec)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"NSE advance/decline unavailable: {exc}")

        index_data: dict[str, float] = {}
        index_change: dict[str, float] = {}
        india_vix: float | None = None
        india_vix_change: float | None = None

        try:
            indices = self._nse.get_all_indices()
            for item in indices:
                name = str(item.get("index") or item.get("indexSymbol") or "").upper()
                last = _to_float(item.get("last") or item.get("lastPrice") or item.get("indexValue"))
                change_pct = _to_float(item.get("percChange") or item.get("percentChange"))

                if "INDIA VIX" in name:
                    india_vix = last
                    india_vix_change = change_pct
                    continue

                for pattern, field in _INDEX_FIELD_MAP.items():
                    if pattern in name:
                        if last is not None:
                            index_data[field] = last
                        if change_pct is not None:
                            index_change[field + "_change_pct"] = change_pct
                        break
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"NSE indices unavailable: {exc}")

        advances = _to_int(breadth.get("advances") or breadth.get("Advances"))
        declines = _to_int(breadth.get("declines") or breadth.get("Declines"))
        unchanged = _to_int(breadth.get("unchanged") or breadth.get("Unchanged"))
        ad_ratio: float | None = None
        if advances is not None and declines is not None and declines > 0:
            ad_ratio = advances / declines

        return MarketBreadthSnapshot(
            as_of=today,
            advances=advances,
            declines=declines,
            unchanged=unchanged,
            advance_decline_ratio=ad_ratio,
            india_vix=india_vix,
            india_vix_change_pct=india_vix_change,
            nifty_50=index_data.get("nifty_50"),
            nifty_50_change_pct=index_change.get("nifty_50_change_pct"),
            sensex=index_data.get("sensex"),
            sensex_change_pct=index_change.get("sensex_change_pct"),
            nifty_bank=index_data.get("nifty_bank"),
            nifty_it=index_data.get("nifty_it"),
            nifty_fmcg=index_data.get("nifty_fmcg"),
            nifty_auto=index_data.get("nifty_auto"),
            nifty_pharma=index_data.get("nifty_pharma"),
            nifty_realty=index_data.get("nifty_realty"),
            nifty_metal=index_data.get("nifty_metal"),
            nifty_energy=index_data.get("nifty_energy"),
            source="NSE",
        )

    # ------------------------------------------------------------------
    # Historical price series with VWAP + delivery % (NSE official)
    # ------------------------------------------------------------------

    def get_historical_prices_official(
        self,
        ticker: str,
        country: Country,
        *,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[PriceBar]:
        symbol = _normalize_symbol(ticker, country)
        fmt_from = from_date.strftime("%d-%m-%Y") if from_date else None
        fmt_to = to_date.strftime("%d-%m-%Y") if to_date else None

        try:
            rows = self._nse.get_historical_price_series(
                symbol, from_date=fmt_from, to_date=fmt_to
            )
            bars = [_nse_hist_row_to_price_bar(row, symbol, country) for row in rows]
            bars = [b for b in bars if b is not None]
            if bars:
                return sorted(bars, key=lambda b: b.date)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"NSE historical price series unavailable for {symbol}: {exc}")

        return []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _board_meeting_events(
        self,
        symbol: str,
        country: Country,
        scripcode: str | None,
        start: date,
        horizon: date,
    ) -> list[EventRecord]:
        rows: list[dict[str, Any]] = []
        try:
            rows = self._nse.get_board_meetings(symbol)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"NSE board meetings unavailable for {symbol}: {exc}")

        if not rows and scripcode:
            try:
                rows = self._bse.get_board_meetings(scripcode)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"BSE board meetings unavailable for {symbol}: {exc}")

        events: list[EventRecord] = []
        for row in rows:
            event_date = _parse_date(
                _first_text(row, "bm_date", "boardMeetingDate", "meetingDate", "date", "BM_DATE")
            )
            if event_date is None or event_date < start or event_date > horizon:
                continue
            headline = _first_text(row, "purpose", "subject", "bm_desc", "description") or "Board meeting"
            lower = headline.lower()
            event_type = (
                EventType.EARNINGS if ("result" in lower or "financial" in lower)
                else EventType.CORPORATE_ACTION
            )
            events.append(
                EventRecord(
                    ticker=symbol,
                    country=country,
                    event_type=event_type,
                    event_date=event_date,
                    meta={"source": "NSE", "headline": headline, "raw": row},
                )
            )
        return events

    def _corporate_action_events(
        self,
        symbol: str,
        country: Country,
        scripcode: str | None,
        start: date,
        horizon: date,
    ) -> list[EventRecord]:
        rows: list[dict[str, Any]] = []
        try:
            rows = self._nse.get_corporate_actions(symbol)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"NSE corporate actions unavailable for {symbol}: {exc}")

        if not rows and scripcode:
            try:
                rows = self._bse.get_corporate_actions(scripcode)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"BSE corporate actions unavailable for {symbol}: {exc}")

        events: list[EventRecord] = []
        for row in rows:
            event_date = _parse_date(
                _first_text(row, "exDate", "ex_date", "recordDate", "record_date", "date", "Ex_Date")
            )
            if event_date is None or event_date < start or event_date > horizon:
                continue
            purpose = _first_text(row, "purpose", "subject", "description", "Purpose") or "Corporate action"
            lower = purpose.lower()
            if "split" in lower or "bonus" in lower:
                event_type = EventType.SPLIT
            elif "dividend" in lower:
                event_type = EventType.EX_DIVIDEND
            else:
                event_type = EventType.CORPORATE_ACTION
            events.append(
                EventRecord(
                    ticker=symbol,
                    country=country,
                    event_type=event_type,
                    event_date=event_date,
                    meta={"source": "NSE", "purpose": purpose, "raw": row},
                )
            )
        return events

    def _scripcode_for(self, symbol: str) -> str | None:
        """Look up the BSE scripcode for a symbol from the stock master."""
        try:
            from pipeline.db.base import get_session
            from pipeline.db.models import Stock
            from sqlalchemy import select

            with get_session() as session:
                row = session.execute(
                    select(Stock.bse_scripcode).where(Stock.ticker == symbol)
                ).scalar_one_or_none()
            return str(row) if row else None
        except Exception:  # noqa: BLE001
            return None

    def _safe_yf_profile(self, ticker: str, country: Country) -> StockProfile | None:
        try:
            return self._yf.get_profile(ticker, country)
        except Exception:  # noqa: BLE001
            return None


# ---------------------------------------------------------------------------
# NSE quote → PriceBar  (with VWAP + delivery %)
# ---------------------------------------------------------------------------

def _quote_to_price_bar(
    payload: dict[str, Any],
    ticker: str,
    country: Country,
) -> PriceBar | None:
    price_info = payload.get("priceInfo") if isinstance(payload.get("priceInfo"), dict) else {}
    security_info = payload.get("securityInfo") if isinstance(payload.get("securityInfo"), dict) else {}
    sec_dp = payload.get("securityWiseDP") if isinstance(payload.get("securityWiseDP"), dict) else {}

    close = _to_float(
        price_info.get("lastPrice")
        or price_info.get("lastPriceString")
        or payload.get("lastPrice")
    )
    if close is None:
        return None

    open_price = _to_float(price_info.get("open")) or close
    high = (
        _to_float(price_info.get("intraDayHighLow", {}).get("max"))
        or _to_float(price_info.get("dayHigh"))
        or close
    )
    low = (
        _to_float(price_info.get("intraDayHighLow", {}).get("min"))
        or _to_float(price_info.get("dayLow"))
        or close
    )
    volume = _to_int(
        security_info.get("totalTradedVolume")
        or sec_dp.get("quantityTraded")
        or price_info.get("totalTradedVolume")
    ) or 0

    # VWAP — NSE provides it directly in priceInfo
    vwap = _to_float(price_info.get("vwap") or price_info.get("VWAP"))

    # Delivery percentage — available in securityWiseDP section
    delivery_pct = _to_float(
        sec_dp.get("deliveryToTradedQuantity")
        or sec_dp.get("deliveryQuantityPct")
    )
    delivery_volume = _to_int(sec_dp.get("deliveryQuantity"))

    quote_dt = _parse_datetime(
        _first_text(price_info, "lastUpdateTime", default=None)
        or _first_text(payload, "lastUpdateTime", default=None)
    )
    quote_date = quote_dt.date() if quote_dt else date.today()

    return PriceBar(
        ticker=ticker,
        country=country,
        date=quote_date,
        open=open_price,
        high=high,
        low=low,
        close=close,
        adj_close=close,
        volume=volume,
        vwap=vwap,
        delivery_pct=delivery_pct,
        delivery_volume=delivery_volume,
    )


def _bse_quote_to_price_bar(
    payload: dict[str, Any],
    ticker: str,
    country: Country,
) -> PriceBar | None:
    close = _to_float(
        payload.get("CurrRate") or payload.get("last_price")
        or payload.get("Currentvalue") or payload.get("TodayClosePrice")
    )
    if close is None:
        return None

    open_price = _to_float(payload.get("Open") or payload.get("open")) or close
    high = _to_float(payload.get("High") or payload.get("high")) or close
    low = _to_float(payload.get("Low") or payload.get("low")) or close
    volume = _to_int(payload.get("TotalTradedQty") or payload.get("Volume")) or 0

    return PriceBar(
        ticker=ticker,
        country=country,
        date=date.today(),
        open=open_price,
        high=high,
        low=low,
        close=close,
        adj_close=close,
        volume=volume,
    )


def _nse_hist_row_to_price_bar(
    row: dict[str, Any],
    ticker: str,
    country: Country,
) -> PriceBar | None:
    trade_date = _parse_date(_first_text(row, "CH_TIMESTAMP", "date", "Date"))
    close = _to_float(row.get("CH_CLOSING_PRICE") or row.get("close") or row.get("Close"))
    if trade_date is None or close is None:
        return None

    open_price = _to_float(row.get("CH_OPENING_PRICE") or row.get("open") or row.get("Open")) or close
    high = _to_float(row.get("CH_TRADE_HIGH_PRICE") or row.get("high") or row.get("High")) or close
    low = _to_float(row.get("CH_TRADE_LOW_PRICE") or row.get("low") or row.get("Low")) or close
    volume = _to_int(row.get("CH_TOT_TRADED_QTY") or row.get("volume") or row.get("Volume")) or 0
    vwap = _to_float(row.get("VWAP") or row.get("CH_VWAP"))
    delivery_pct = _to_float(row.get("COP_DELIV_PERC") or row.get("deliveryPct"))
    delivery_volume = _to_int(row.get("COP_DELIV_QTY") or row.get("deliveryQty"))

    return PriceBar(
        ticker=ticker,
        country=country,
        date=trade_date,
        open=open_price,
        high=high,
        low=low,
        close=close,
        adj_close=close,
        volume=volume,
        vwap=vwap,
        delivery_pct=delivery_pct,
        delivery_volume=delivery_volume,
    )


# ---------------------------------------------------------------------------
# Bulk / block deals
# ---------------------------------------------------------------------------

def _nse_deal_to_record(
    row: dict[str, Any],
    ticker: str,
    country: Country,
    deal_type: str,
) -> BulkDealRecord | None:
    trade_date = _parse_date(_first_text(row, "DATE1", "date", "tradeDate", "Deal_Date"))
    if trade_date is None:
        return None
    return BulkDealRecord(
        ticker=ticker,
        country=country,
        deal_type=deal_type,
        trade_date=trade_date,
        client_name=_first_text(row, "CLIENT_NAME", "clientName", "Client_Name"),
        transaction_type=_first_text(row, "BUY_SELL", "buySell", "Transaction_Type"),
        quantity=_to_float(row.get("QTY_TRD") or row.get("quantity") or row.get("Quantity")),
        trade_price=_to_float(row.get("TRADE_PRICE") or row.get("tradePrice") or row.get("Price")),
        source="NSE",
        raw=row,
    )


def _bse_deal_to_record(
    row: dict[str, Any],
    ticker: str,
    country: Country,
    deal_type: str,
) -> BulkDealRecord | None:
    trade_date = _parse_date(_first_text(row, "Deal_Date", "date", "Date"))
    if trade_date is None:
        return None
    return BulkDealRecord(
        ticker=ticker,
        country=country,
        deal_type=deal_type,
        trade_date=trade_date,
        client_name=_first_text(row, "Client_Name", "clientName"),
        transaction_type=_first_text(row, "BuySell", "Transaction_Type"),
        quantity=_to_float(row.get("Quantity") or row.get("qty")),
        trade_price=_to_float(row.get("Price") or row.get("price")),
        source="BSE",
        raw=row,
    )


# ---------------------------------------------------------------------------
# Insider trades
# ---------------------------------------------------------------------------

def _nse_insider_to_record(
    row: dict[str, Any],
    ticker: str,
    country: Country,
) -> InsiderTradeRecord | None:
    return InsiderTradeRecord(
        ticker=ticker,
        country=country,
        person_name=_first_text(row, "acqName", "name", "personName"),
        person_category=_first_text(row, "personCategory", "category", "acqType"),
        transaction_type=_first_text(row, "acqMode", "transactionType", "mode"),
        trade_date=_parse_date(_first_text(row, "date", "tradingDate")),
        from_date=_parse_date(_first_text(row, "befAcqSharesNo", "fromDate")),
        to_date=_parse_date(_first_text(row, "aftAcqSharesNo", "toDate")),
        shares_traded=_to_float(row.get("noOfShares") or row.get("shares")),
        trade_price=_to_float(row.get("acquiredPrice") or row.get("price")),
        post_trade_pct=_to_float(row.get("aftAcqSharesPerc") or row.get("postHoldingPct")),
        source="NSE",
        raw=row,
    )


def _bse_insider_to_record(
    row: dict[str, Any],
    ticker: str,
    country: Country,
) -> InsiderTradeRecord | None:
    return InsiderTradeRecord(
        ticker=ticker,
        country=country,
        person_name=_first_text(row, "AcquirerName", "Name"),
        person_category=_first_text(row, "Category", "PersonCategory"),
        transaction_type=_first_text(row, "AcquisitionDisposal", "TransactionType"),
        trade_date=_parse_date(_first_text(row, "DateOfAllotment", "Date")),
        from_date=None,
        to_date=_parse_date(_first_text(row, "DateOfAllotment", "Date")),
        shares_traded=_to_float(row.get("NoOfShares") or row.get("Shares")),
        trade_price=_to_float(row.get("AcquisitionPrice") or row.get("Price")),
        post_trade_pct=_to_float(row.get("PostAcquistionShareholding")),
        source="BSE",
        raw=row,
    )


# ---------------------------------------------------------------------------
# Market depth
# ---------------------------------------------------------------------------

def _nse_depth_to_snapshot(
    raw: dict[str, Any],
    ticker: str,
    country: Country,
) -> MarketDepthSnapshot | None:
    if not raw:
        return None

    buy_raw = raw.get("buy") or raw.get("Buy") or []
    sell_raw = raw.get("sell") or raw.get("Sell") or []

    if not isinstance(buy_raw, list) or not isinstance(sell_raw, list):
        return None

    def _parse_levels(levels: list) -> list[MarketDepthLevel]:
        result = []
        for lvl in levels[:5]:
            if not isinstance(lvl, dict):
                continue
            price = _to_float(lvl.get("price") or lvl.get("Price"))
            qty = _to_int(lvl.get("quantity") or lvl.get("Quantity"))
            if price is not None and qty is not None:
                result.append(MarketDepthLevel(
                    price=price,
                    quantity=qty,
                    orders=_to_int(lvl.get("orders") or lvl.get("Orders")),
                ))
        return result

    buy_depth = _parse_levels(buy_raw)
    sell_depth = _parse_levels(sell_raw)

    if not buy_depth and not sell_depth:
        return None

    return MarketDepthSnapshot(
        ticker=ticker,
        country=country,
        snapshot_at=datetime.now(),
        buy_depth=buy_depth,
        sell_depth=sell_depth,
        total_buy_qty=_to_int(raw.get("totalBuyQuantity") or raw.get("TotalBuyQty")),
        total_sell_qty=_to_int(raw.get("totalSellQuantity") or raw.get("TotalSellQty")),
        source="NSE",
    )


def _bse_depth_from_graph(
    payload: dict[str, Any],
    ticker: str,
    country: Country,
) -> MarketDepthSnapshot | None:
    depth = payload.get("Depth") or payload.get("depth")
    if not isinstance(depth, dict):
        return None
    return _nse_depth_to_snapshot(depth, ticker, country)


# ---------------------------------------------------------------------------
# Derivatives / option chain → DerivativesSentiment
# ---------------------------------------------------------------------------

def _option_chain_to_sentiment(
    chain: dict[str, Any],
    ticker: str,
    country: Country,
) -> DerivativesSentiment | None:
    if not chain:
        return None

    records = chain.get("records") or {}
    data = records.get("data") or chain.get("data") or []
    underlying_value = _to_float(
        records.get("underlyingValue") or chain.get("underlyingValue")
    )
    exp_dates = records.get("expiryDates") or chain.get("expiryDates") or []

    total_call_oi: float = 0.0
    total_put_oi: float = 0.0
    max_call_oi: float = 0.0
    max_put_oi: float = 0.0
    top_call_strike: float | None = None
    top_put_strike: float | None = None
    atm_ce_iv: float | None = None
    atm_pe_iv: float | None = None

    # Use nearest expiry only for PCR/max-pain
    nearest_exp = exp_dates[0] if exp_dates else None

    for item in data:
        if not isinstance(item, dict):
            continue
        if nearest_exp and item.get("expiryDate") != nearest_exp:
            continue

        strike = _to_float(item.get("strikePrice"))
        ce = item.get("CE") or {}
        pe = item.get("PE") or {}

        ce_oi = _to_float(ce.get("openInterest")) or 0.0
        pe_oi = _to_float(pe.get("openInterest")) or 0.0
        total_call_oi += ce_oi
        total_put_oi += pe_oi

        if ce_oi > max_call_oi:
            max_call_oi = ce_oi
            top_call_strike = strike
        if pe_oi > max_put_oi:
            max_put_oi = pe_oi
            top_put_strike = strike

        # ATM IV: pick the strike closest to underlying
        if underlying_value and strike and abs(strike - underlying_value) < (underlying_value * 0.01):
            atm_ce_iv = _to_float(ce.get("impliedVolatility"))
            atm_pe_iv = _to_float(pe.get("impliedVolatility"))

    pcr = (total_put_oi / total_call_oi) if total_call_oi > 0 else None
    atm_iv = (
        ((atm_ce_iv or 0) + (atm_pe_iv or 0)) / 2
        if atm_ce_iv is not None or atm_pe_iv is not None
        else None
    )

    # Max pain: strike where total option value (losses to buyers) is highest
    max_pain_strike = _compute_max_pain(data, nearest_exp)

    return DerivativesSentiment(
        ticker=ticker,
        country=country,
        as_of=date.today(),
        oi_call_total=total_call_oi or None,
        oi_put_total=total_put_oi or None,
        put_call_ratio=pcr,
        max_pain_strike=max_pain_strike,
        atm_iv=atm_iv,
        top_call_oi_strike=top_call_strike,
        top_put_oi_strike=top_put_strike,
        source="NSE",
        raw_summary={"underlying": underlying_value, "expiry": nearest_exp},
    )


def _compute_max_pain(data: list[dict[str, Any]], expiry: str | None) -> float | None:
    """Max pain: strike at which total option buyer losses are maximized.

    For each candidate strike S, sum |OI(CE) * (S - K)| for K < S (calls in-the-money)
    and |OI(PE) * (K - S)| for K > S (puts in-the-money).
    """
    strikes: list[float] = []
    oi_by_strike: dict[float, tuple[float, float]] = {}  # strike → (call_oi, put_oi)

    for item in data:
        if not isinstance(item, dict):
            continue
        if expiry and item.get("expiryDate") != expiry:
            continue
        strike = _to_float(item.get("strikePrice"))
        if strike is None:
            continue
        ce = item.get("CE") or {}
        pe = item.get("PE") or {}
        ce_oi = _to_float(ce.get("openInterest")) or 0.0
        pe_oi = _to_float(pe.get("openInterest")) or 0.0
        oi_by_strike[strike] = (ce_oi, pe_oi)
        strikes.append(strike)

    if not strikes:
        return None

    min_pain = float("inf")
    max_pain_strike = None

    for candidate in sorted(set(strikes)):
        pain = 0.0
        for strike, (ce_oi, pe_oi) in oi_by_strike.items():
            if candidate > strike:
                pain += ce_oi * (candidate - strike)
            elif candidate < strike:
                pain += pe_oi * (strike - candidate)
        if pain < min_pain:
            min_pain = pain
            max_pain_strike = candidate

    return max_pain_strike


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _normalize_symbol(ticker: str, country: Country) -> str:
    if country != Country.INDIA:
        raise SymbolNotFoundError(ticker, PROVIDER_NAME)
    return str(ticker).strip().upper().replace(".NS", "").replace(".BO", "")


def _market_cap_from_quote(payload: dict[str, Any]) -> float | None:
    if not isinstance(payload, dict):
        return None
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    security_info = payload.get("securityInfo") if isinstance(payload.get("securityInfo"), dict) else {}
    direct = _to_float(
        metadata.get("marketCap")
        or security_info.get("marketCap")
        or payload.get("marketCap")
    )
    if direct is not None:
        return direct
    issued_size = _to_float(
        metadata.get("issuedSize")
        or security_info.get("issuedCap")
        or security_info.get("issuedSize")
    )
    last_price = _to_float(
        (payload.get("priceInfo") or {}).get("lastPrice")
        if isinstance(payload.get("priceInfo"), dict) else None
    )
    if issued_size is not None and last_price is not None:
        return issued_size * last_price
    return None


def _announcement_url(row: dict[str, Any], symbol: str) -> str:
    attachment = _first_text(row, "attchmntFile", "attachment", "pdfFile", default=None)
    if attachment:
        attachment = attachment.strip()
        if attachment.startswith("http://") or attachment.startswith("https://"):
            return attachment
        if attachment.startswith("/"):
            return f"{_NSE_BASE}{attachment}"
        return f"{_NSE_BASE}/{attachment.lstrip('/')}"
    identifier = (
        _first_text(row, "announcementId", "id", "seqId", default=None)
        or _first_text(row, "subject", "desc", default=symbol)
    )
    return f"{_ANNOUNCEMENTS_PAGE}?symbol={symbol}&ref={identifier}"


def _first_text(row: dict[str, Any], *keys: str, default: str | None = None) -> str | None:
    for key in keys:
        value = row.get(key)
        if value in (None, ""):
            continue
        text = str(value).strip()
        if text:
            return text
    return default


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    parsed = pd.to_datetime(value, errors="coerce", dayfirst=True)
    if parsed is None or pd.isna(parsed):
        return None
    if isinstance(parsed, pd.Timestamp):
        return parsed.to_pydatetime().replace(tzinfo=None)
    return None


def _parse_date(value: Any) -> date | None:
    parsed = _parse_datetime(value)
    return parsed.date() if parsed else None


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        clean = value.replace(",", "").strip()
        if not clean:
            return None
        value = clean
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    numeric = _to_float(value)
    return int(numeric) if numeric is not None else None
