"""Official India fundamentals provider.

This is the first slice of the hybrid India data lane:
- Reads official-source India financial/shareholding exports from disk
- Normalizes them into `FundamentalSnapshot`
- Computes common ratios locally when the source rows do not provide them

The provider intentionally sits in front of vendor fundamentals for India.
If no official file is present for a ticker, the registry falls back to the
existing FMP/yfinance lane.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger

from pipeline.config import settings
from pipeline.db.enums import Country
from pipeline.providers.dto import FundamentalSnapshot
from pipeline.providers.errors import DataProviderError, SymbolNotFoundError

PROVIDER_NAME = "india_official"


class IndiaOfficialFundamentalsProvider:
    """Load India fundamentals from official NSE/BSE exports on disk."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or settings.official_india_data_dir

    def get_quarterly_fundamentals(
        self, ticker: str, country: Country, limit: int = 20
    ) -> list[FundamentalSnapshot]:
        if country != Country.INDIA:
            raise SymbolNotFoundError(ticker, PROVIDER_NAME)

        rows, source = self._load_rows("financials", ticker)
        if not rows:
            raise SymbolNotFoundError(ticker, PROVIDER_NAME)

        shareholding_rows, _ = self._load_rows("shareholding", ticker)
        promoter_history = _parse_promoter_history(shareholding_rows)
        shareholding_details = _parse_shareholding_detail(shareholding_rows)

        snapshots = [
            snapshot
            for snapshot in (
                _row_to_snapshot(ticker, country, row, promoter_history, shareholding_details)
                for row in rows
            )
            if snapshot is not None
        ]

        # Data quality: deduplicate quarters (keep first/most-complete occurrence)
        snapshots = _deduplicate_quarters(snapshots)

        if not snapshots:
            raise DataProviderError(
                f"{PROVIDER_NAME} found files for '{ticker}' but could not parse any quarterly rows."
            )

        snapshots.sort(key=lambda snap: snap.fiscal_date, reverse=True)
        logger.debug(f"[{PROVIDER_NAME}] loaded {len(snapshots)} quarters for {ticker} from {source}")
        return snapshots[:limit]

    def _load_rows(self, kind: str, ticker: str) -> tuple[list[dict[str, Any]], str | None]:
        for path in self._candidate_paths(kind, ticker):
            if not path.exists():
                continue
            try:
                if path.suffix.lower() == ".json":
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    rows = _rows_from_payload(payload, kind)
                elif path.suffix.lower() == ".csv":
                    rows = pd.read_csv(path).to_dict(orient="records")
                else:
                    continue
            except Exception as exc:  # noqa: BLE001
                raise DataProviderError(
                    f"{PROVIDER_NAME} failed to parse {kind} file '{path}': {exc}"
                ) from exc

            normalized = [row for row in rows if isinstance(row, dict)]
            if normalized:
                return normalized, str(path)
        return [], None

    def _candidate_paths(self, kind: str, ticker: str) -> list[Path]:
        return [
            self.data_dir / "nse" / kind / f"{ticker}.json",
            self.data_dir / "nse" / kind / f"{ticker}.csv",
            self.data_dir / "bse" / kind / f"{ticker}.json",
            self.data_dir / "bse" / kind / f"{ticker}.csv",
            self.data_dir / kind / f"{ticker}.json",
            self.data_dir / kind / f"{ticker}.csv",
        ]


def _rows_from_payload(payload: Any, kind: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]

    if not isinstance(payload, dict):
        return []

    keys = [kind, "rows", "data", "items", "financials", "shareholding"]
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]

    return [payload]


def _parse_promoter_history(rows: list[dict[str, Any]]) -> list[tuple[date, float]]:
    history: list[tuple[date, float]] = []
    for row in rows:
        as_of = _parse_date(
            _first_present(
                row,
                "as_of_date",
                "fiscal_date",
                "date",
                "period_end",
                "periodEnded",
                default=None,
            )
        )
        promoter = _first_num(
            row,
            "promoter_holding",
            "promoter_pct",
            "promoter_percentage",
            "promoters",
            "promoter",
        )
        if as_of is not None and promoter is not None:
            history.append((as_of, promoter))
    history.sort(key=lambda item: item[0], reverse=True)
    return history


# ---------------------------------------------------------------------------
# Shareholding detail parsing (FII, DII, pledge)
# ---------------------------------------------------------------------------

@dataclass
class _ShareholdingDetail:
    as_of: date
    promoter_pct: float | None = None
    promoter_pledge_pct: float | None = None
    fii_pct: float | None = None
    dii_pct: float | None = None
    public_pct: float | None = None


def _parse_shareholding_detail(rows: list[dict[str, Any]]) -> list[_ShareholdingDetail]:
    """Extract FII, DII, promoter, and pledge breakdown from official shareholding rows."""
    details: list[_ShareholdingDetail] = []
    for row in rows:
        as_of = _parse_date(
            _first_present(row, "as_of_date", "fiscal_date", "date", "period_end", default=None)
        )
        if as_of is None:
            continue

        promoter_pct = _first_num(row, "promoter_holding", "promoter_pct", "promoter_percentage", "promoters", "promoter")
        # Pledge — NSE includes this in shareholding master under pr_and_prgrp or pledge fields
        pledge_pct = _first_num(
            row,
            "promoter_pledge_pct",
            "pledge_pct",
            "pledgePct",
            "pledge_percentage",
            "pledgePercentage",
        )
        # FII / DII — from shareholding row if available
        fii_pct = _first_num(row, "fii", "fii_pct", "foreign_institutional", "fiis", "FII")
        dii_pct = _first_num(row, "dii", "dii_pct", "domestic_institutional", "diis", "DII", "mutual_funds")
        public_pct = _first_num(row, "public_pct", "public_val", "public", "public_shareholders")

        details.append(_ShareholdingDetail(
            as_of=as_of,
            promoter_pct=promoter_pct,
            promoter_pledge_pct=pledge_pct,
            fii_pct=fii_pct,
            dii_pct=dii_pct,
            public_pct=public_pct,
        ))

    details.sort(key=lambda d: d.as_of, reverse=True)
    return details


def _shareholding_for_date(
    fiscal_date: date,
    details: list[_ShareholdingDetail],
) -> _ShareholdingDetail | None:
    """Return the most recent shareholding detail at or before fiscal_date."""
    if not details:
        return None
    for detail in details:
        if detail.as_of <= fiscal_date:
            return detail
    return details[0]


def _promoter_for_date(
    fiscal_date: date,
    history: list[tuple[date, float]],
) -> float | None:
    if not history:
        return None
    for as_of, promoter in history:
        if as_of <= fiscal_date:
            return promoter
    return history[0][1]


def _row_to_snapshot(
    ticker: str,
    country: Country,
    row: dict[str, Any],
    promoter_history: list[tuple[date, float]],
    shareholding_details: list[_ShareholdingDetail] | None = None,
) -> FundamentalSnapshot | None:
    fiscal_date = _parse_date(
        _first_present(
            row,
            "fiscal_date",
            "period_ended",
            "period_end",
            "periodEnded",
            "date",
            "quarter_end",
            default=None,
        )
    )
    if fiscal_date is None:
        return None

    revenue = _first_num(row, "revenue", "total_revenue", "sales", "net_sales")
    net_income = _first_num(
        row,
        "net_income",
        "profit_after_tax",
        "pat",
        "net_profit",
        "profit",
    )
    eps = _first_num(row, "eps", "earnings_per_share", "basic_eps", "diluted_eps")
    total_debt = _first_num(row, "total_debt", "debt", "borrowings", "net_debt")
    total_equity = _first_num(
        row,
        "total_equity",
        "shareholders_equity",
        "equity",
        "net_worth",
        "networth",
    )
    operating_cash_flow = _first_num(
        row,
        "operating_cash_flow",
        "cash_from_operations",
        "net_cash_from_operating_activities",
        "ocf",
    )
    free_cash_flow = _first_num(row, "free_cash_flow", "fcf")
    if free_cash_flow is None and operating_cash_flow is not None:
        capex = _first_num(row, "capital_expenditure", "capex")
        if capex is not None:
            free_cash_flow = operating_cash_flow - abs(capex)

    gross_profit = _first_num(row, "gross_profit")
    operating_profit = _first_num(row, "operating_profit", "operating_income", "ebit")
    ebit = _first_num(row, "ebit", "operating_profit", "operating_income")
    ebitda = _first_num(row, "ebitda")
    enterprise_value = _first_num(row, "enterprise_value", "ev")
    market_cap = _first_num(row, "market_cap")
    close_price = _first_num(row, "close_price", "price", "market_price")
    book_value_per_share = _first_num(row, "book_value_per_share", "bvps")
    dividend_per_share = _first_num(row, "dividend_per_share", "dps", "dividend")
    dividends_paid = _first_num(row, "dividends_paid", "dividend_paid")
    cash_and_equivalents = _first_num(
        row,
        "cash_and_equivalents",
        "cash",
        "cash_balance",
    )

    debt_equity = _first_num(row, "debt_equity")
    if debt_equity is None and total_debt is not None and total_equity not in (None, 0):
        debt_equity = total_debt / total_equity

    roe = _first_num(row, "roe")
    if roe is None and net_income is not None and total_equity not in (None, 0):
        roe = (net_income / total_equity) * 100

    capital_employed = _first_num(row, "capital_employed")
    if capital_employed is None and total_equity is not None:
        capital_employed = total_equity + (total_debt or 0) - (cash_and_equivalents or 0)
    roce = _first_num(row, "roce")
    if roce is None and ebit is not None and capital_employed not in (None, 0):
        roce = (ebit / capital_employed) * 100

    gross_margin = _first_num(row, "gross_margin")
    if gross_margin is None and gross_profit is not None and revenue not in (None, 0):
        gross_margin = (gross_profit / revenue) * 100

    operating_margin = _first_num(row, "operating_margin")
    if operating_margin is None and operating_profit is not None and revenue not in (None, 0):
        operating_margin = (operating_profit / revenue) * 100

    net_margin = _first_num(row, "net_margin")
    if net_margin is None and net_income is not None and revenue not in (None, 0):
        net_margin = (net_income / revenue) * 100

    pe = _first_num(row, "pe", "price_to_earnings", "pe_ratio")
    if pe is None:
        if close_price is not None and eps not in (None, 0):
            pe = close_price / eps
        elif market_cap is not None and net_income not in (None, 0):
            pe = market_cap / net_income

    peg = _first_num(row, "peg", "peg_ratio")

    pb = _first_num(row, "pb", "price_to_book", "pb_ratio")
    if pb is None:
        if close_price is not None and book_value_per_share not in (None, 0):
            pb = close_price / book_value_per_share
        elif market_cap is not None and total_equity not in (None, 0):
            pb = market_cap / total_equity

    ev_ebitda = _first_num(row, "ev_ebitda", "ev_to_ebitda")
    if ev_ebitda is None and enterprise_value is not None and ebitda not in (None, 0):
        ev_ebitda = enterprise_value / ebitda

    dividend_yield = _first_num(row, "dividend_yield")
    if dividend_yield is None and dividend_per_share is not None and close_price not in (None, 0):
        dividend_yield = (dividend_per_share / close_price) * 100

    payout_ratio = _first_num(row, "payout_ratio")
    if payout_ratio is None:
        if dividends_paid is not None and net_income not in (None, 0):
            payout_ratio = dividends_paid / net_income
        elif dividend_per_share is not None and eps not in (None, 0):
            payout_ratio = dividend_per_share / eps

    promoter_holding = _first_num(row, "promoter_holding", "promoter_pct", "promoter_percentage")
    if promoter_holding is None:
        promoter_holding = _first_num(row, "promoter")
    if promoter_holding is None:
        promoter_holding = _promoter_for_date(fiscal_date, promoter_history)

    # FII / DII / pledge — from shareholding detail closest to this fiscal date
    sh_detail = _shareholding_for_date(fiscal_date, shareholding_details or [])
    promoter_pledge_pct = _first_num(row, "promoter_pledge_pct", "pledge_pct") or (
        sh_detail.promoter_pledge_pct if sh_detail else None
    )
    fii_holding = _first_num(row, "fii", "fii_pct", "foreign_institutional") or (
        sh_detail.fii_pct if sh_detail else None
    )
    dii_holding = _first_num(row, "dii", "dii_pct", "domestic_institutional") or (
        sh_detail.dii_pct if sh_detail else None
    )

    # Consolidated / standalone flag
    consolidated_raw = _first_present(row, "consolidated", "is_consolidated", "statement_type", default=None)
    is_consolidated: bool | None = None
    if consolidated_raw is not None:
        consolidated_str = str(consolidated_raw).strip().lower()
        if consolidated_str in ("consolidated", "true", "1", "yes", "con"):
            is_consolidated = True
        elif consolidated_str in ("standalone", "false", "0", "no", "std"):
            is_consolidated = False

    # Data source tag
    data_source = str(_first_present(row, "source", "data_source", default="nse") or "nse").lower()

    # India sector-specific fields (banks / NBFCs)
    gnpa_pct = _first_num(row, "gnpa_pct", "gnpa", "gross_npa_pct", "gross_npa_percentage")
    nnpa_pct = _first_num(row, "nnpa_pct", "nnpa", "net_npa_pct", "net_npa_percentage")
    nim_pct = _first_num(row, "nim_pct", "nim", "net_interest_margin")
    casa_ratio = _first_num(row, "casa_ratio", "casa", "casa_pct")
    credit_cost = _first_num(row, "credit_cost", "credit_cost_pct")
    capital_adequacy_ratio = _first_num(
        row, "capital_adequacy_ratio", "car", "crar", "capital_adequacy"
    )

    period = _first_present(row, "period", "period_label", default=None)
    if not period:
        period = f"{fiscal_date.year}Q{((fiscal_date.month - 1) // 3) + 1}"

    return FundamentalSnapshot(
        ticker=ticker,
        country=country,
        fiscal_date=fiscal_date,
        period=str(period),
        revenue=revenue,
        net_income=net_income,
        eps=eps,
        total_debt=total_debt,
        total_equity=total_equity,
        debt_equity=debt_equity,
        operating_cash_flow=operating_cash_flow,
        free_cash_flow=free_cash_flow,
        roe=roe,
        roce=roce,
        gross_margin=gross_margin,
        operating_margin=operating_margin,
        net_margin=net_margin,
        pe=pe,
        peg=peg,
        pb=pb,
        ev_ebitda=ev_ebitda,
        dividend_per_share=dividend_per_share,
        dividend_yield=dividend_yield,
        payout_ratio=payout_ratio,
        promoter_holding=promoter_holding,
        promoter_pledge_pct=promoter_pledge_pct,
        fii_holding=fii_holding,
        dii_holding=dii_holding,
        is_consolidated=is_consolidated,
        data_source=data_source,
        gnpa_pct=gnpa_pct,
        nnpa_pct=nnpa_pct,
        nim_pct=nim_pct,
        casa_ratio=casa_ratio,
        credit_cost=credit_cost,
        capital_adequacy_ratio=capital_adequacy_ratio,
    )


def _deduplicate_quarters(
    snapshots: list[FundamentalSnapshot],
) -> list[FundamentalSnapshot]:
    """Keep one snapshot per fiscal_date, preferring the more complete row.

    'More complete' = fewer None fields. This handles cases where NSE returns
    both consolidated and standalone rows for the same period — we keep
    whichever has more populated fields.
    """
    by_date: dict[date, FundamentalSnapshot] = {}
    for snap in snapshots:
        existing = by_date.get(snap.fiscal_date)
        if existing is None:
            by_date[snap.fiscal_date] = snap
        else:
            # Count non-None fields; prefer consolidated over standalone when tied
            existing_score = sum(
                1 for f in existing.model_fields if getattr(existing, f) is not None
            )
            new_score = sum(
                1 for f in snap.model_fields if getattr(snap, f) is not None
            )
            if new_score > existing_score or (
                new_score == existing_score and snap.is_consolidated is True
            ):
                by_date[snap.fiscal_date] = snap
    return list(by_date.values())


def _first_present(row: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, "") and not _is_nan(value):
            return value
    return default


def _first_num(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _num(row.get(key))
        if value is not None:
            return value
    return None


def _num(value: Any) -> float | None:
    if value is None or value == "" or _is_nan(value):
        return None
    if isinstance(value, str):
        clean = value.strip().replace(",", "")
        if clean.endswith("%"):
            clean = clean[:-1]
        if not clean:
            return None
        value = clean
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_date(value: Any) -> date | None:
    if value is None or value == "" or _is_nan(value):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        parsed = pd.to_datetime(value, errors="coerce")
    except Exception:  # noqa: BLE001
        return None
    if parsed is None or pd.isna(parsed):
        return None
    return parsed.date()


def _is_nan(value: Any) -> bool:
    try:
        return bool(pd.isna(value))
    except Exception:  # noqa: BLE001
        return False
