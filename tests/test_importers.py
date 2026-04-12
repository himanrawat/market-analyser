from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pipeline.cli import app
from pipeline.importers.india_official import (
    OfficialIndiaBatchFetchResult,
    OfficialIndiaImportResult,
    fetch_nse_official_batch,
    fetch_nse_official_bundle,
    import_official_india_bundle,
)


def test_import_official_india_bundle_filters_and_normalizes_csv(tmp_path: Path) -> None:
    financials = tmp_path / "nse_financials.csv"
    financials.write_text(
        (
            "Symbol,Period Ended,Revenue,Net Income,EPS,Total Debt,Total Equity\n"
            "RELIANCE,2025-12-31,1000,100,10,200,500\n"
            "INFY,2025-12-31,900,90,9,50,400\n"
        ),
        encoding="utf-8",
    )
    shareholding = tmp_path / "nse_shareholding.json"
    shareholding.write_text(
        json.dumps(
            {
                "rows": [
                    {"Symbol": "RELIANCE", "As Of Date": "2025-12-31", "Promoter %": 52.1},
                    {"Symbol": "INFY", "As Of Date": "2025-12-31", "Promoter %": 13.2},
                ]
            }
        ),
        encoding="utf-8",
    )

    result = import_official_india_bundle(
        ticker="RELIANCE",
        source="nse",
        financials=financials,
        shareholding=shareholding,
        output_dir=tmp_path / "official_india",
    )

    assert result.row_counts == {"financials": 1, "shareholding": 1}

    payload = json.loads((tmp_path / "official_india" / "nse" / "financials" / "RELIANCE.json").read_text())
    assert payload["ticker"] == "RELIANCE"
    assert payload["source"] == "nse"
    assert payload["financials"][0]["symbol"] == "RELIANCE"
    assert payload["financials"][0]["period_ended"] == "2025-12-31"
    assert payload["financials"][0]["total_equity"] == 500

    shp = json.loads((tmp_path / "official_india" / "nse" / "shareholding" / "RELIANCE.json").read_text())
    assert shp["shareholding"][0]["promoter"] == 52.1


def test_import_official_india_bundle_accepts_rows_without_ticker_column(tmp_path: Path) -> None:
    financials = tmp_path / "single_company.json"
    financials.write_text(
        json.dumps(
            {
                "financials": [
                    {
                        "Fiscal Date": "2025-09-30",
                        "Revenue": 2000,
                        "Net Income": 300,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = import_official_india_bundle(
        ticker="TCS",
        source="nse",
        financials=financials,
        output_dir=tmp_path / "official_india",
    )

    assert result.row_counts["financials"] == 1
    payload = json.loads((tmp_path / "official_india" / "nse" / "financials" / "TCS.json").read_text())
    assert payload["financials"][0]["fiscal_date"] == "2025-09-30"


def test_import_india_official_cli(tmp_path: Path) -> None:
    financials = tmp_path / "reliance.csv"
    financials.write_text(
        "Symbol,Period Ended,Revenue,Net Income\nRELIANCE,2025-12-31,1000,100\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "import-india-official",
            "--ticker",
            "RELIANCE",
            "--source",
            "nse",
            "--financials",
            str(financials),
            "--output-dir",
            str(tmp_path / "official_india"),
        ],
    )

    assert result.exit_code == 0
    assert "Imported official India files for RELIANCE" in result.stdout
    assert (tmp_path / "official_india" / "nse" / "financials" / "RELIANCE.json").exists()


class _FakeNSEClient:
    def get_equity_meta(self, symbol: str) -> dict[str, object]:
        return {"symbol": symbol, "companyName": f"{symbol} Industries Limited"}

    def get_financial_results_master(self, symbol: str, *, period: str = "Quarterly") -> list[dict[str, object]]:
        assert period == "Quarterly"
        return [
            {
                "symbol": symbol,
                "companyName": f"{symbol} Industries Limited",
                "period": "Quarterly",
                "relatingTo": "Third Quarter",
                "financialYear": "01-Apr-2024 To 31-Mar-2025",
                "toDate": "31-Dec-2024",
                "fromDate": "01-Oct-2024",
                "seqNumber": "2",
                "params": "consolidated-row",
                "consolidated": "Consolidated",
                "audited": "Un-Audited",
                "cumulative": "Non-cumulative",
                "indAs": "Ind-AS New",
                "reInd": "N",
                "oldNewFlag": "N",
                "format": "New",
                "industry": "-",
                "xbrl": "https://example.com/consolidated.xml",
                "filingDate": "16-Jan-2025 20:15",
                "broadCastDate": "16-Jan-2025 20:15:20",
                "isin": "INE002A01018",
            },
            {
                "symbol": symbol,
                "companyName": f"{symbol} Industries Limited",
                "period": "Quarterly",
                "relatingTo": "Third Quarter",
                "financialYear": "01-Apr-2024 To 31-Mar-2025",
                "toDate": "31-Dec-2024",
                "fromDate": "01-Oct-2024",
                "seqNumber": "1",
                "params": "standalone-row",
                "consolidated": "Non-Consolidated",
                "audited": "Un-Audited",
                "cumulative": "Non-cumulative",
                "indAs": "Ind-AS New",
                "reInd": "N",
                "oldNewFlag": "N",
                "format": "New",
                "industry": "-",
                "xbrl": "https://example.com/standalone.xml",
                "filingDate": "16-Jan-2025 20:20",
                "broadCastDate": "16-Jan-2025 20:20:21",
                "isin": "INE002A01018",
            },
        ]

    def get_financial_result_detail(self, master_row: dict[str, object]) -> dict[str, object]:
        seq = str(master_row["seqNumber"])
        payloads = {
            "1": {
                "periodEndDT": "31-Dec-2024",
                "attachment_filename": "https://example.com/standalone.zip",
                "resultsData2": {
                    "re_net_sale": "12826000",
                    "re_total_inc": "13147400",
                    "re_proloss_ord_act": "872100",
                    "re_basic_eps_for_cont_dic_opr": "6.44",
                    "re_pro_loss_bef_tax": "1159700",
                    "re_pro_bef_int_n_excep": "1159700",
                    "re_int_new": "237100",
                    "re_tax": "287600",
                    "re_depr_und_exp": "445900",
                    "re_face_val": "10",
                },
            },
            "2": {
                "periodEndDT": "31-Dec-2024",
                "attachment_filename": "https://example.com/consolidated.zip",
                "resultsData2": {
                    "re_net_sale": "13000000",
                    "re_total_inc": "13300000",
                    "re_proloss_ord_act": "900000",
                    "re_basic_eps_for_cont_dic_opr": "7.10",
                    "re_pro_loss_bef_tax": "1200000",
                    "re_pro_bef_int_n_excep": "1200000",
                    "re_int_new": "200000",
                    "re_tax": "300000",
                    "re_depr_und_exp": "400000",
                    "re_face_val": "10",
                },
            },
        }
        return payloads[seq]

    def get_shareholding_master(self, symbol: str) -> list[dict[str, object]]:
        return [
            {
                "symbol": symbol,
                "name": f"{symbol} Industries Limited",
                "date": "31-DEC-2024",
                "pr_and_prgrp": "50.13",
                "public_val": "49.87",
                "employeeTrusts": "0",
                "underlyingDrs": "0",
                "recordId": "195954",
                "submissionDate": "21-JAN-2025",
                "broadcastDate": "21-JAN-2025 16:55:29",
                "xbrl": "https://example.com/shp.xml",
                "newColumn": False,
                "remarksWeb": "N",
                "revisedData": "N",
                "revisionDate": None,
            }
        ]


def test_fetch_nse_official_bundle_writes_canonical_payloads(tmp_path: Path) -> None:
    result = fetch_nse_official_bundle(
        ticker="RELIANCE",
        limit=4,
        output_dir=tmp_path / "official_india",
        client=_FakeNSEClient(),
        statement_scope="consolidated",
    )

    assert result.row_counts == {"financials": 1, "shareholding": 1}

    financials_payload = json.loads(
        (tmp_path / "official_india" / "nse" / "financials" / "RELIANCE.json").read_text()
    )
    row = financials_payload["financials"][0]
    assert row["fiscal_date"] == "31-Dec-2024"
    assert row["consolidated"] == "Consolidated"
    assert row["revenue"] == 13000000.0
    assert row["net_income"] == 900000.0
    assert row["eps"] == 7.1
    assert row["attachment_filename"] == "https://example.com/consolidated.zip"

    shareholding_payload = json.loads(
        (tmp_path / "official_india" / "nse" / "shareholding" / "RELIANCE.json").read_text()
    )
    shp = shareholding_payload["shareholding"][0]
    assert shp["as_of_date"] == "31-DEC-2024"
    assert shp["promoter_pct"] == 50.13
    assert shp["public_pct"] == 49.87


def test_fetch_nse_official_batch_writes_multiple_tickers(tmp_path: Path) -> None:
    result = fetch_nse_official_batch(
        tickers=["RELIANCE", "TCS", "RELIANCE"],
        limit=2,
        output_dir=tmp_path / "official_india",
        client=_FakeNSEClient(),
        statement_scope="standalone",
    )

    assert result.requested_tickers == ("RELIANCE", "TCS")
    assert len(result.completed) == 2
    assert not result.failed
    payload = json.loads(
        (tmp_path / "official_india" / "nse" / "financials" / "TCS.json").read_text()
    )
    assert payload["ticker"] == "TCS"
    assert payload["financials"][0]["consolidated"] == "Non-Consolidated"
    assert payload["financials"][0]["eps"] == 6.44


def test_fetch_india_official_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    expected = OfficialIndiaImportResult(
        ticker="RELIANCE",
        source="nse",
        imported_kinds=("financials", "shareholding"),
        output_paths=(
            tmp_path / "official_india" / "nse" / "financials" / "RELIANCE.json",
            tmp_path / "official_india" / "nse" / "shareholding" / "RELIANCE.json",
        ),
        row_counts={"financials": 4, "shareholding": 4},
    )

    def _fake_fetch(**_: object) -> OfficialIndiaImportResult:
        return expected

    monkeypatch.setattr("pipeline.cli.fetch_nse_official_bundle", _fake_fetch)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "fetch-india-official",
            "--ticker",
            "RELIANCE",
            "--limit",
            "4",
            "--statement-scope",
            "standalone",
            "--output-dir",
            str(tmp_path / "official_india"),
        ],
    )

    assert result.exit_code == 0
    assert "Fetched official India files for RELIANCE" in result.stdout


def test_fetch_india_official_batch_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = OfficialIndiaBatchFetchResult(
        requested_tickers=("RELIANCE", "TCS"),
        completed=(
            OfficialIndiaImportResult(
                ticker="RELIANCE",
                source="nse",
                imported_kinds=("financials", "shareholding"),
                output_paths=(),
                row_counts={"financials": 8, "shareholding": 8},
            ),
            OfficialIndiaImportResult(
                ticker="TCS",
                source="nse",
                imported_kinds=("financials", "shareholding"),
                output_paths=(),
                row_counts={"financials": 8, "shareholding": 8},
            ),
        ),
        failed=(),
    )

    def _fake_fetch(**_: object) -> OfficialIndiaBatchFetchResult:
        return expected

    monkeypatch.setattr("pipeline.cli.fetch_nse_official_batch", _fake_fetch)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "fetch-india-official-batch",
            "RELIANCE",
            "TCS",
            "--limit",
            "8",
        ],
    )

    assert result.exit_code == 0
    assert "Fetched official India batch" in result.stdout
    assert "RELIANCE" in result.stdout
    assert "TCS" in result.stdout
