"""Importer for official India financial/shareholding files.

This importer normalizes downloaded NSE/BSE CSV/JSON files into the canonical
`data/official_india/<source>/<kind>/<ticker>.json` layout consumed by the
hybrid India fundamentals provider.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from pipeline.config import settings

_SOURCE_CHOICES = {"nse", "bse"}
_KIND_CHOICES = {"financials", "shareholding"}
_NSE_BASE_URL = "https://www.nseindia.com"
_STATEMENT_SCOPE_CHOICES = {"consolidated", "standalone", "latest"}
_TICKER_KEYS = (
    "ticker",
    "symbol",
    "nse_symbol",
    "bse_symbol",
    "security",
    "company_symbol",
    "tradingsymbol",
)


@dataclass(frozen=True)
class OfficialIndiaImportResult:
    ticker: str
    source: str
    imported_kinds: tuple[str, ...]
    output_paths: tuple[Path, ...]
    row_counts: dict[str, int]


@dataclass(frozen=True)
class OfficialIndiaBatchFetchResult:
    requested_tickers: tuple[str, ...]
    completed: tuple[OfficialIndiaImportResult, ...]
    failed: tuple[tuple[str, str], ...]


def import_official_india_bundle(
    *,
    ticker: str,
    source: str,
    financials: Path | None = None,
    shareholding: Path | None = None,
    output_dir: Path | None = None,
) -> OfficialIndiaImportResult:
    """Import one ticker's official India files into canonical JSON payloads."""
    clean_ticker = _normalize_ticker(ticker)
    source_name = source.strip().lower()
    if source_name not in _SOURCE_CHOICES:
        raise ValueError(f"Unsupported source '{source}'. Expected one of {_SOURCE_CHOICES}.")

    if financials is None and shareholding is None:
        raise ValueError("At least one of 'financials' or 'shareholding' is required.")

    root = output_dir or settings.official_india_data_dir
    imported_kinds: list[str] = []
    output_paths: list[Path] = []
    row_counts: dict[str, int] = {}

    if financials is not None:
        path, count = _import_one(
            ticker=clean_ticker,
            source=source_name,
            kind="financials",
            input_path=financials,
            output_dir=root,
        )
        imported_kinds.append("financials")
        output_paths.append(path)
        row_counts["financials"] = count

    if shareholding is not None:
        path, count = _import_one(
            ticker=clean_ticker,
            source=source_name,
            kind="shareholding",
            input_path=shareholding,
            output_dir=root,
        )
        imported_kinds.append("shareholding")
        output_paths.append(path)
        row_counts["shareholding"] = count

    return OfficialIndiaImportResult(
        ticker=clean_ticker,
        source=source_name,
        imported_kinds=tuple(imported_kinds),
        output_paths=tuple(output_paths),
        row_counts=row_counts,
    )


def fetch_nse_official_bundle(
    *,
    ticker: str,
    limit: int = 8,
    financials: bool = True,
    shareholding: bool = True,
    statement_scope: str = "consolidated",
    output_dir: Path | None = None,
    client: NSEOfficialClient | None = None,
) -> OfficialIndiaImportResult:
    """Fetch live NSE data and write canonical JSON consumed by the hybrid lane."""
    clean_ticker = _normalize_ticker(ticker)
    if not financials and not shareholding:
        raise ValueError("At least one of 'financials' or 'shareholding' must be enabled.")

    scope = statement_scope.strip().lower()
    if scope not in _STATEMENT_SCOPE_CHOICES:
        raise ValueError(
            f"Unsupported statement scope '{statement_scope}'. "
            f"Expected one of {sorted(_STATEMENT_SCOPE_CHOICES)}."
        )

    live_client = client or NSEOfficialClient()
    root = output_dir or settings.official_india_data_dir

    imported_kinds: list[str] = []
    output_paths: list[Path] = []
    row_counts: dict[str, int] = {}

    meta = live_client.get_equity_meta(clean_ticker)
    symbol = _normalize_ticker(meta.get("symbol") or clean_ticker)

    if financials:
        master_rows = live_client.get_financial_results_master(symbol, period="Quarterly")
        selected_rows = _select_financial_result_rows(master_rows, limit=limit, statement_scope=scope)
        financial_rows = [
            _build_nse_financial_row(master_row, live_client.get_financial_result_detail(master_row))
            for master_row in selected_rows
        ]
        path, count = _write_payload(
            ticker=symbol,
            source="nse",
            kind="financials",
            rows=financial_rows,
            output_dir=root,
            source_reference=f"{_NSE_BASE_URL}/api/corporates-financial-results",
        )
        imported_kinds.append("financials")
        output_paths.append(path)
        row_counts["financials"] = count

    if shareholding:
        shareholding_rows = live_client.get_shareholding_master(symbol)
        shareholding_payload = [
            _build_nse_shareholding_row(row)
            for row in shareholding_rows[: max(limit, 1)]
        ]
        path, count = _write_payload(
            ticker=symbol,
            source="nse",
            kind="shareholding",
            rows=shareholding_payload,
            output_dir=root,
            source_reference=f"{_NSE_BASE_URL}/api/corporate-share-holdings-master",
        )
        imported_kinds.append("shareholding")
        output_paths.append(path)
        row_counts["shareholding"] = count

    return OfficialIndiaImportResult(
        ticker=symbol,
        source="nse",
        imported_kinds=tuple(imported_kinds),
        output_paths=tuple(output_paths),
        row_counts=row_counts,
    )


def fetch_nse_official_batch(
    *,
    tickers: list[str] | tuple[str, ...],
    limit: int = 8,
    financials: bool = True,
    shareholding: bool = True,
    statement_scope: str = "consolidated",
    output_dir: Path | None = None,
    client: NSEOfficialClient | None = None,
    continue_on_error: bool = True,
) -> OfficialIndiaBatchFetchResult:
    """Fetch live NSE data for multiple tickers into the canonical hybrid lane."""
    normalized_tickers = _dedupe_tickers(tickers)
    if not normalized_tickers:
        raise ValueError("At least one ticker is required.")

    live_client = client or NSEOfficialClient()
    completed: list[OfficialIndiaImportResult] = []
    failed: list[tuple[str, str]] = []

    for ticker in normalized_tickers:
        try:
            result = fetch_nse_official_bundle(
                ticker=ticker,
                limit=limit,
                financials=financials,
                shareholding=shareholding,
                statement_scope=statement_scope,
                output_dir=output_dir,
                client=live_client,
            )
            completed.append(result)
        except Exception as exc:  # noqa: BLE001
            failed.append((ticker, str(exc)))
            if not continue_on_error:
                break

    return OfficialIndiaBatchFetchResult(
        requested_tickers=tuple(normalized_tickers),
        completed=tuple(completed),
        failed=tuple(failed),
    )


def _import_one(
    *,
    ticker: str,
    source: str,
    kind: str,
    input_path: Path,
    output_dir: Path,
) -> tuple[Path, int]:
    if kind not in _KIND_CHOICES:
        raise ValueError(f"Unsupported kind '{kind}'. Expected one of {_KIND_CHOICES}.")
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    rows = _read_rows(input_path)
    filtered = _filter_rows_for_ticker(rows, ticker)
    normalized = [_normalize_row(row) for row in filtered]
    return _write_payload(
        ticker=ticker,
        source=source,
        kind=kind,
        rows=normalized,
        output_dir=output_dir,
        source_file=str(input_path),
    )


def _write_payload(
    *,
    ticker: str,
    source: str,
    kind: str,
    rows: list[dict[str, Any]],
    output_dir: Path,
    source_file: str | None = None,
    source_reference: str | None = None,
) -> tuple[Path, int]:
    payload = {
        "ticker": ticker,
        "source": source,
        kind: rows,
        "imported_at": datetime.now(UTC).replace(tzinfo=None).isoformat(),
        "source_file": source_file,
        "source_reference": source_reference,
    }

    target = output_dir / source / kind / f"{ticker}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return target, len(rows)


def _read_rows(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path).to_dict(orient="records")
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return _rows_from_payload(payload)
    raise ValueError(f"Unsupported file type '{path.suffix}' for {path}.")


def _rows_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("rows", "data", "items", "financials", "shareholding"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    return [payload]


def _filter_rows_for_ticker(rows: list[dict[str, Any]], ticker: str) -> list[dict[str, Any]]:
    if not rows:
        return []

    present_keys = {
        _normalize_key(key)
        for row in rows
        for key in row
    }
    candidate_keys = [key for key in _TICKER_KEYS if key in present_keys]
    if not candidate_keys:
        return rows

    filtered = [
        row
        for row in rows
        if any(_normalize_ticker(row.get(key)) == ticker for key in row if _normalize_key(key) in candidate_keys)
    ]
    return filtered or rows


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in row.items():
        normalized[_normalize_key(str(key))] = _normalize_value(value)
    return normalized


def _normalize_key(key: str) -> str:
    key = key.strip()
    key = re.sub(r"[%()/\-]+", " ", key)
    key = re.sub(r"[^a-zA-Z0-9\s]+", "", key)
    key = re.sub(r"\s+", "_", key.strip())
    return key.lower()


def _normalize_value(value: Any) -> Any:
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _normalize_value(v) for k, v in value.items()}
    if isinstance(value, str):
        clean = value.strip()
        return clean
    if pd.isna(value):
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except TypeError:
            pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:  # noqa: BLE001
            pass
    return value


def _normalize_ticker(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().upper().replace(".NS", "").replace(".BO", "")


def _dedupe_tickers(values: list[str] | tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        ticker = _normalize_ticker(value)
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        result.append(ticker)
    return result


def _select_financial_result_rows(
    rows: list[dict[str, Any]],
    *,
    limit: int,
    statement_scope: str,
) -> list[dict[str, Any]]:
    if not rows:
        return []

    selected: list[dict[str, Any]] = []
    seen_periods: set[str] = set()

    for row in rows:
        period_key = str(row.get("toDate") or row.get("periodEndDT") or row.get("params") or "")
        if not period_key or period_key in seen_periods:
            continue

        same_period = [
            candidate
            for candidate in rows
            if str(candidate.get("toDate") or candidate.get("periodEndDT") or candidate.get("params") or "") == period_key
        ]
        chosen = _choose_financial_row(same_period, statement_scope)
        selected.append(chosen)
        seen_periods.add(period_key)
        if len(selected) >= max(limit, 1):
            break

    return selected


def _choose_financial_row(rows: list[dict[str, Any]], statement_scope: str) -> dict[str, Any]:
    if not rows:
        return {}
    if statement_scope == "latest":
        return rows[0]

    want_consolidated = statement_scope == "consolidated"
    for row in rows:
        consolidated = str(row.get("consolidated") or "").strip().lower()
        is_consolidated = consolidated == "consolidated"
        if is_consolidated == want_consolidated:
            return row
    return rows[0]


def _build_nse_financial_row(
    master_row: dict[str, Any],
    detail_payload: dict[str, Any],
) -> dict[str, Any]:
    detail = detail_payload.get("resultsData2") or detail_payload.get("resultsData") or {}
    fiscal_date = detail_payload.get("periodEndDT") or master_row.get("toDate")
    revenue = _pick_num(detail, "re_net_sale", "re_total_inc")
    net_income = _pick_num(
        detail,
        "re_proloss_ord_act",
        "dis_opr_aftr_tax_plus_ord_act",
        "re_con_pro_loss",
    )
    eps = _pick_num(
        detail,
        "re_basic_eps_for_cont_dic_opr",
        "re_bsc_eps_bfr_exi",
        "re_dilut_eps_for_cont_dic_opr",
        "re_basic_eps",
    )

    row = {
        "symbol": master_row.get("symbol"),
        "company_name": master_row.get("companyName"),
        "fiscal_date": fiscal_date,
        "period": master_row.get("relatingTo") or master_row.get("period"),
        "financial_year": master_row.get("financialYear"),
        "from_date": master_row.get("fromDate"),
        "to_date": master_row.get("toDate"),
        "audited": master_row.get("audited"),
        "cumulative": master_row.get("cumulative"),
        "consolidated": master_row.get("consolidated"),
        "ind_as": master_row.get("indAs"),
        "re_ind": master_row.get("reInd"),
        "filing_date": master_row.get("filingDate"),
        "broadcast_date": master_row.get("broadCastDate"),
        "isin": master_row.get("isin"),
        "xbrl": master_row.get("xbrl"),
        "attachment_filename": detail_payload.get("attachment_filename"),
        "seq_number": master_row.get("seqNumber") or detail_payload.get("seqnum"),
        "params": master_row.get("params"),
        "format": master_row.get("format"),
        "industry": master_row.get("industry"),
        "revenue": revenue,
        "net_income": net_income,
        "eps": eps,
        "total_income": _pick_num(detail, "re_total_inc"),
        "profit_before_tax": _pick_num(detail, "re_pro_loss_bef_tax"),
        "ebit": _pick_num(detail, "re_pro_bef_int_n_excep"),
        "operating_profit": _pick_num(detail, "re_pro_bef_int_n_excep"),
        "interest_expense": _pick_num(detail, "re_int_new"),
        "tax_expense": _pick_num(detail, "re_tax", "re_curr_tax"),
        "depreciation": _pick_num(detail, "re_depr_und_exp"),
        "other_income": _pick_num(detail, "re_oth_inc_new"),
        "raw_material_consumption": _pick_num(detail, "re_rawmat_consump"),
        "purchase_of_traded_goods": _pick_num(detail, "re_pur_trd_goods"),
        "staff_cost": _pick_num(detail, "re_staff_cost"),
        "other_expense": _pick_num(detail, "re_oth_exp"),
        "total_expense": _pick_num(detail, "re_oth_tot_exp"),
        "face_value": _pick_num(detail, "re_face_val"),
        "debt_equity": _pick_num(detail, "re_debt_eqt_rat"),
        "interest_coverage": _pick_num(detail, "re_int_ser_cov"),
        "debt_service_coverage": _pick_num(detail, "re_debt_ser_cov"),
        "nse_results_data": detail,
        "nse_notes": detail_payload.get("notes"),
    }
    return {key: value for key, value in row.items() if value not in (None, "")}


def _build_nse_shareholding_row(row: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "symbol": row.get("symbol"),
        "company_name": row.get("name"),
        "as_of_date": row.get("date"),
        "promoter_pct": _to_num(row.get("pr_and_prgrp")),
        "public_pct": _to_num(row.get("public_val")),
        "underlying_drs_pct": _to_num(row.get("underlyingDrs")),
        "employee_trusts_pct": _to_num(row.get("employeeTrusts")),
        "record_id": row.get("recordId"),
        "submission_date": row.get("submissionDate"),
        "broadcast_date": row.get("broadcastDate"),
        "xbrl": row.get("xbrl"),
        "new_column": row.get("newColumn"),
        "remarks_web": row.get("remarksWeb"),
        "revised_data": row.get("revisedData"),
        "revision_date": row.get("revisionDate"),
    }
    return {key: value for key, value in payload.items() if value not in (None, "")}


def _pick_num(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _to_num(row.get(key))
        if value is not None:
            return value
    return None


def _to_num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        clean = value.strip().replace(",", "")
        if not clean:
            return None
        value = clean
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class NSEOfficialClient:
    """Resilient live client for NSE corporate filings, market data, and derivatives APIs.

    Uses the hardened IndiaHTTPClient underneath for cookie management,
    rate limiting, retry, and raw payload preservation.
    """

    def __init__(
        self,
        session: requests.Session | None = None,
        *,
        base_url: str = _NSE_BASE_URL,
        timeout: float = 30.0,
        preserve_raw: bool = False,
    ) -> None:
        from pipeline.providers.india_http import IndiaHTTPClient  # avoid circular at module level

        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._http = IndiaHTTPClient(
            session=session,
            timeout=timeout,
            preserve_raw=preserve_raw,
        )

    # ------------------------------------------------------------------
    # Fundamentals and shareholding (existing, now via hardened client)
    # ------------------------------------------------------------------

    def get_equity_meta(self, symbol: str) -> dict[str, Any]:
        payload = self._nse("/api/equity-meta-info", params={"symbol": symbol})
        if not isinstance(payload, dict) or not payload.get("symbol"):
            raise RuntimeError(f"NSE did not return equity metadata for '{symbol}'.")
        return payload

    def get_financial_results_master(
        self,
        symbol: str,
        *,
        period: str = "Quarterly",
    ) -> list[dict[str, Any]]:
        payload = self._nse(
            "/api/corporates-financial-results",
            params={"index": "equities", "symbol": symbol, "period": period},
        )
        if not isinstance(payload, list):
            raise RuntimeError(f"NSE financial results response was not a list for '{symbol}'.")
        return [row for row in payload if isinstance(row, dict)]

    def get_financial_result_detail(self, master_row: dict[str, Any]) -> dict[str, Any]:
        params = {
            "index": "equities",
            "params": master_row.get("params"),
            "seq_id": master_row.get("seqNumber"),
            "industry": master_row.get("industry"),
            "frOldNewFlag": master_row.get("oldNewFlag"),
            "ind": master_row.get("reInd"),
            "format": master_row.get("format"),
        }
        payload = self._nse("/api/corporates-financial-results-data", params=params)
        if not isinstance(payload, dict):
            raise RuntimeError(
                f"NSE filing detail response was not an object for seq '{master_row.get('seqNumber')}'."
            )
        return payload

    def get_shareholding_master(self, symbol: str) -> list[dict[str, Any]]:
        payload = self._nse(
            "/api/corporate-share-holdings-master",
            params={"index": "equities", "symbol": symbol},
        )
        if not isinstance(payload, list):
            raise RuntimeError(f"NSE shareholding response was not a list for '{symbol}'.")
        return [row for row in payload if isinstance(row, dict)]

    # ------------------------------------------------------------------
    # Quote and market data
    # ------------------------------------------------------------------

    def get_quote_equity(self, symbol: str) -> dict[str, Any]:
        payload = self._nse("/api/quote-equity", params={"symbol": symbol})
        if not isinstance(payload, dict):
            raise RuntimeError(f"NSE quote-equity response was not an object for '{symbol}'.")
        return payload

    def get_quote_derivative(self, symbol: str) -> dict[str, Any]:
        """F&O quote for a symbol (futures + options top-line)."""
        payload = self._nse("/api/quote-derivative", params={"symbol": symbol})
        return payload if isinstance(payload, dict) else {}

    # ------------------------------------------------------------------
    # Market depth / order book
    # ------------------------------------------------------------------

    def get_market_depth(self, symbol: str) -> dict[str, Any]:
        """Top-5 bid/ask depth from NSE quote endpoint.

        NSE embeds depth data inside the quote-equity response under `marketDeptOrderBook`.
        Returns empty dict if the endpoint does not expose depth for this symbol.
        """
        try:
            quote = self.get_quote_equity(symbol)
        except Exception:  # noqa: BLE001
            return {}
        depth = quote.get("marketDeptOrderBook")
        if isinstance(depth, dict):
            return depth
        # Some NSE responses nest it differently
        price_info = quote.get("priceInfo") or {}
        return price_info.get("marketDeptOrderBook") or {}

    # ------------------------------------------------------------------
    # Corporate events
    # ------------------------------------------------------------------

    def get_corporate_announcements(self, symbol: str | None = None) -> list[dict[str, Any]]:
        payload = self._nse(
            "/api/corporate-announcements",
            params=self._equity_params(symbol),
        )
        if not isinstance(payload, list):
            raise RuntimeError("NSE corporate announcements response was not a list.")
        return [row for row in payload if isinstance(row, dict)]

    def get_board_meetings(self, symbol: str | None = None) -> list[dict[str, Any]]:
        payload = self._nse(
            "/api/corporate-board-meetings",
            params=self._equity_params(symbol),
        )
        if not isinstance(payload, list):
            raise RuntimeError("NSE board meetings response was not a list.")
        return [row for row in payload if isinstance(row, dict)]

    def get_corporate_actions(self, symbol: str | None = None) -> list[dict[str, Any]]:
        payload = self._nse(
            "/api/corporate-actions",
            params=self._equity_params(symbol),
        )
        if not isinstance(payload, list):
            raise RuntimeError("NSE corporate actions response was not a list.")
        return [row for row in payload if isinstance(row, dict)]

    # ------------------------------------------------------------------
    # Bulk and block deals
    # ------------------------------------------------------------------

    def get_bulk_deals(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """Bulk deal disclosures. Returns all recent bulk deals; filter by symbol if given."""
        payload = self._nse("/api/bulk-deals", params=self._equity_params(symbol))
        rows = _unwrap_list(payload)
        if symbol:
            sym_upper = symbol.upper()
            rows = [r for r in rows if str(r.get("symbol") or r.get("Symbol") or "").upper() == sym_upper]
        return rows

    def get_block_deals(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """Block deal disclosures."""
        payload = self._nse("/api/block-deals", params=self._equity_params(symbol))
        rows = _unwrap_list(payload)
        if symbol:
            sym_upper = symbol.upper()
            rows = [r for r in rows if str(r.get("symbol") or r.get("Symbol") or "").upper() == sym_upper]
        return rows

    # ------------------------------------------------------------------
    # Insider trading
    # ------------------------------------------------------------------

    def get_insider_trades(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """SEBI insider trading disclosures (SAST/PIT regulations)."""
        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol
        payload = self._nse("/api/corporate-insider-trading", params=params or None)
        return _unwrap_list(payload)

    # ------------------------------------------------------------------
    # Derivatives (F&O)
    # ------------------------------------------------------------------

    def get_option_chain(self, symbol: str) -> dict[str, Any]:
        """Full NSE option chain for a symbol (indices and stocks in F&O)."""
        payload = self._nse("/api/option-chain-equities", params={"symbol": symbol})
        return payload if isinstance(payload, dict) else {}

    def get_option_chain_index(self, index_symbol: str = "NIFTY") -> dict[str, Any]:
        """Full NSE option chain for an index (NIFTY, BANKNIFTY, etc.)."""
        payload = self._nse("/api/option-chain-indices", params={"symbol": index_symbol})
        return payload if isinstance(payload, dict) else {}

    # ------------------------------------------------------------------
    # Index and market-wide data
    # ------------------------------------------------------------------

    def get_india_vix(self) -> dict[str, Any]:
        """India VIX spot value and change."""
        payload = self._nse("/api/allIndices")
        if isinstance(payload, dict):
            indices = payload.get("data") or []
            for item in indices:
                if isinstance(item, dict) and "INDIA VIX" in str(item.get("index") or item.get("indexSymbol") or ""):
                    return item
        return {}

    def get_all_indices(self) -> list[dict[str, Any]]:
        """All NSE indices with latest quote data (NIFTY 50, BANKNIFTY, sector indices)."""
        payload = self._nse("/api/allIndices")
        if isinstance(payload, dict):
            return [row for row in (payload.get("data") or []) if isinstance(row, dict)]
        return []

    def get_advance_decline(self) -> dict[str, Any]:
        """Market breadth: advance/decline ratio across NSE."""
        payload = self._nse("/api/advance-decline")
        return payload if isinstance(payload, dict) else {}

    def get_fno_ban_list(self) -> dict[str, Any]:
        """Stocks currently in the F&O ban period (NSE F-ban list)."""
        payload = self._nse("/api/fo-ban-lot-size")
        return payload if isinstance(payload, dict) else {}

    def get_asm_list(self) -> dict[str, Any]:
        """Stocks on the ASM (Additional Surveillance Measure) list."""
        payload = self._nse("/api/reportASM")
        return payload if isinstance(payload, dict) else {}

    # ------------------------------------------------------------------
    # Historical price data (bhavcopy-style)
    # ------------------------------------------------------------------

    def get_historical_price_series(
        self,
        symbol: str,
        *,
        series: str = "EQ",
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Historical daily OHLCV series from NSE with delivery percentage.

        from_date / to_date format: DD-MM-YYYY
        """
        params: dict[str, Any] = {"symbol": symbol, "series": series}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        payload = self._nse("/api/historical/cm/equity", params=params)
        if isinstance(payload, dict):
            return _unwrap_list(payload.get("data") or payload)
        return _unwrap_list(payload)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _nse(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._http.nse_get_json(path, params=params)

    @staticmethod
    def _equity_params(symbol: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"index": "equities"}
        if symbol:
            params["symbol"] = symbol
        return params


class BSEOfficialClient:
    """Resilient live client for BSE public APIs.

    BSE is used as the NSE fallback lane for quotes, corporate events,
    bulk/block deals, and insider disclosures.

    BSE endpoints commonly key by `scripcode` (e.g. 500325 for Reliance).
    The caller is responsible for providing the correct scripcode from the
    stock master identifiers (bse_scripcode).
    """

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        preserve_raw: bool = False,
    ) -> None:
        from pipeline.providers.india_http import IndiaHTTPClient

        self._http = IndiaHTTPClient(timeout=timeout, preserve_raw=preserve_raw)

    # ------------------------------------------------------------------
    # Quote and price data
    # ------------------------------------------------------------------

    def get_price_graph(self, scripcode: str) -> dict[str, Any]:
        """Latest + recent historical price data for a BSE scripcode."""
        payload = self._bse(
            "/BseIndiaAPI/api/StockReachGraph/w",
            params={"scripcode": scripcode},
        )
        return payload if isinstance(payload, dict) else {}

    def get_stock_quote(self, scripcode: str) -> dict[str, Any]:
        """Latest quote for a BSE scripcode."""
        payload = self._bse(
            "/BseIndiaAPI/api/getScripHeaderData/w",
            params={"Scripcode": scripcode},
        )
        return payload if isinstance(payload, dict) else {}

    # ------------------------------------------------------------------
    # Corporate events
    # ------------------------------------------------------------------

    def get_corporate_announcements(
        self,
        scripcode: str | None = None,
        *,
        category: str = "Company Update",
        page: int = 1,
    ) -> list[dict[str, Any]]:
        """BSE corporate announcements. If scripcode given, filter to that stock."""
        params: dict[str, Any] = {
            "pageno": page,
            "strCat": category,
        }
        if scripcode:
            params["scripcode"] = scripcode
        payload = self._bse(
            "/BseIndiaAPI/api/AnnSubCategoryGetData/w",
            params=params,
        )
        return _unwrap_list(payload)

    def get_corporate_actions(self, scripcode: str) -> list[dict[str, Any]]:
        """BSE corporate actions (dividends, bonus, splits, rights) for a scripcode."""
        payload = self._bse(
            "/BseIndiaAPI/api/CorporateAction/w",
            params={"scripcode": scripcode},
        )
        return _unwrap_list(payload)

    def get_board_meetings(self, scripcode: str) -> list[dict[str, Any]]:
        """BSE board meeting schedule for a scripcode."""
        payload = self._bse(
            "/BseIndiaAPI/api/BoardMeeting/w",
            params={"scripcode": scripcode},
        )
        return _unwrap_list(payload)

    # ------------------------------------------------------------------
    # Bulk and block deals
    # ------------------------------------------------------------------

    def get_bulk_deals(self, scripcode: str | None = None) -> list[dict[str, Any]]:
        """BSE bulk deal disclosures."""
        params: dict[str, Any] = {}
        if scripcode:
            params["scripcode"] = scripcode
        payload = self._bse("/BseIndiaAPI/api/BulkDealData/w", params=params or None)
        return _unwrap_list(payload)

    def get_block_deals(self, scripcode: str | None = None) -> list[dict[str, Any]]:
        """BSE block deal disclosures."""
        params: dict[str, Any] = {}
        if scripcode:
            params["scripcode"] = scripcode
        payload = self._bse("/BseIndiaAPI/api/BlockDealData/w", params=params or None)
        return _unwrap_list(payload)

    # ------------------------------------------------------------------
    # Insider trading
    # ------------------------------------------------------------------

    def get_insider_trades(self, scripcode: str | None = None) -> list[dict[str, Any]]:
        """BSE insider trading disclosures (SAST/PIT)."""
        params: dict[str, Any] = {}
        if scripcode:
            params["scripcode"] = scripcode
        payload = self._bse("/BseIndiaAPI/api/InsiderTradingData/w", params=params or None)
        return _unwrap_list(payload)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _bse(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._http.bse_get_json(path, params=params)


def _unwrap_list(payload: Any) -> list[dict[str, Any]]:
    """Extract a list of dicts from a response payload that may be wrapped."""
    if payload is None:
        return []
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("data", "Data", "rows", "items", "deals", "records", "Table", "Table1"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return []
