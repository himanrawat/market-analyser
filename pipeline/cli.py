"""Typer CLI entry point for the pipeline.

Usage:
    python -m pipeline.cli init-db
    python -m pipeline.cli show-tables
    python -m pipeline.cli run [--fresh-capital 15000] [--picks 10] [--date 2026-04-06]

Cron (6th of each month, 20:00 server time):
    0 20 6 * * /path/to/.venv/bin/python -m pipeline.cli run
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

import typer
from loguru import logger
from rich.console import Console
from rich.table import Table
from sqlalchemy import inspect

from pipeline.db import init_db
from pipeline.db.base import get_engine
from pipeline.importers import (
    fetch_nse_official_batch,
    fetch_nse_official_bundle,
    import_official_india_bundle,
)
from pipeline.logging_setup import configure_logging

app = typer.Typer(add_completion=False, no_args_is_help=True)
console = Console()


@app.callback()
def _bootstrap() -> None:
    configure_logging()


@app.command("init-db")
def init_db_cmd() -> None:
    """Create all tables. Idempotent."""
    logger.info("Initializing database…")
    init_db()
    logger.info("Database initialized.")
    show_tables()


@app.command("show-tables")
def show_tables() -> None:
    """List tables and column counts."""
    inspector = inspect(get_engine())
    table = Table(title="Database schema")
    table.add_column("Table", style="cyan")
    table.add_column("Columns", justify="right", style="magenta")
    table.add_column("Indexes", justify="right", style="green")
    for name in sorted(inspector.get_table_names()):
        cols = len(inspector.get_columns(name))
        idx = len(inspector.get_indexes(name))
        table.add_row(name, str(cols), str(idx))
    console.print(table)


@app.command("run")
def run_cmd(
    fresh_capital: float = typer.Option(0.0, "--fresh-capital", "-c",
                                         help="Fresh capital to deploy (INR or USD)"),
    picks: int = typer.Option(10, "--picks", "-n",
                              help="Stocks per bucket (default 10)"),
    run_date: Optional[str] = typer.Option(None, "--date", "-d",
                                            help="Override run date YYYY-MM-DD"),
) -> None:
    """Run the full monthly rebalance pipeline."""
    from pipeline.scheduler import run_pipeline
    parsed_date = date.fromisoformat(run_date) if run_date else None
    run_pipeline(as_of=parsed_date, fresh_capital=fresh_capital, picks_per_bucket=picks)


@app.command("import-india-official")
def import_india_official_cmd(
    ticker: str = typer.Option(..., "--ticker", "-t", help="Ticker symbol, e.g. RELIANCE"),
    source: str = typer.Option("nse", "--source", "-s", help="Source: nse or bse"),
    financials: Optional[Path] = typer.Option(
        None,
        "--financials",
        help="Path to downloaded official financials CSV/JSON file",
    ),
    shareholding: Optional[Path] = typer.Option(
        None,
        "--shareholding",
        help="Path to downloaded official shareholding CSV/JSON file",
    ),
    output_dir: Optional[Path] = typer.Option(
        None,
        "--output-dir",
        help="Override canonical output directory (defaults to OFFICIAL_INDIA_DATA_DIR)",
    ),
) -> None:
    """Import official NSE/BSE files into the hybrid India data lane."""
    try:
        result = import_official_india_bundle(
            ticker=ticker,
            source=source,
            financials=financials,
            shareholding=shareholding,
            output_dir=output_dir,
        )
    except Exception as exc:  # noqa: BLE001
        raise typer.BadParameter(str(exc)) from exc

    table = Table(title=f"Imported official India files for {result.ticker}")
    table.add_column("Kind", style="cyan")
    table.add_column("Rows", justify="right", style="magenta")
    table.add_column("Output", style="green")
    for kind, path in zip(result.imported_kinds, result.output_paths):
        table.add_row(kind, str(result.row_counts.get(kind, 0)), str(path))
    console.print(table)
    logger.info(
        f"Imported official India files for {result.ticker} from {result.source}: "
        f"{', '.join(result.imported_kinds)}"
    )


@app.command("fetch-india-official")
def fetch_india_official_cmd(
    ticker: str = typer.Option(..., "--ticker", "-t", help="Ticker symbol, e.g. RELIANCE"),
    limit: int = typer.Option(8, "--limit", "-n", help="Number of recent quarters/periods to fetch"),
    financials: bool = typer.Option(
        True,
        "--financials/--no-financials",
        help="Fetch live NSE quarterly financial results",
    ),
    shareholding: bool = typer.Option(
        True,
        "--shareholding/--no-shareholding",
        help="Fetch live NSE shareholding rows",
    ),
    statement_scope: str = typer.Option(
        "consolidated",
        "--statement-scope",
        help="One of: consolidated, standalone, latest",
    ),
    output_dir: Optional[Path] = typer.Option(
        None,
        "--output-dir",
        help="Override canonical output directory (defaults to OFFICIAL_INDIA_DATA_DIR)",
    ),
) -> None:
    """Fetch live NSE data directly into the hybrid India data lane."""
    try:
        result = fetch_nse_official_bundle(
            ticker=ticker,
            limit=limit,
            financials=financials,
            shareholding=shareholding,
            statement_scope=statement_scope,
            output_dir=output_dir,
        )
    except Exception as exc:  # noqa: BLE001
        raise typer.BadParameter(str(exc)) from exc

    table = Table(title=f"Fetched official India files for {result.ticker}")
    table.add_column("Kind", style="cyan")
    table.add_column("Rows", justify="right", style="magenta")
    table.add_column("Output", style="green")
    for kind, path in zip(result.imported_kinds, result.output_paths):
        table.add_row(kind, str(result.row_counts.get(kind, 0)), str(path))
    console.print(table)
    logger.info(
        f"Fetched official India files for {result.ticker} from {result.source}: "
        f"{', '.join(result.imported_kinds)}"
    )


@app.command("fetch-india-official-batch")
def fetch_india_official_batch_cmd(
    tickers: list[str] = typer.Argument(..., help="Ticker symbols, e.g. RELIANCE TCS INFY"),
    limit: int = typer.Option(8, "--limit", "-n", help="Number of recent quarters/periods to fetch"),
    financials: bool = typer.Option(
        True,
        "--financials/--no-financials",
        help="Fetch live NSE quarterly financial results",
    ),
    shareholding: bool = typer.Option(
        True,
        "--shareholding/--no-shareholding",
        help="Fetch live NSE shareholding rows",
    ),
    statement_scope: str = typer.Option(
        "consolidated",
        "--statement-scope",
        help="One of: consolidated, standalone, latest",
    ),
    output_dir: Optional[Path] = typer.Option(
        None,
        "--output-dir",
        help="Override canonical output directory (defaults to OFFICIAL_INDIA_DATA_DIR)",
    ),
) -> None:
    """Fetch live NSE data for multiple India tickers into the hybrid data lane."""
    try:
        result = fetch_nse_official_batch(
            tickers=tickers,
            limit=limit,
            financials=financials,
            shareholding=shareholding,
            statement_scope=statement_scope,
            output_dir=output_dir,
        )
    except Exception as exc:  # noqa: BLE001
        raise typer.BadParameter(str(exc)) from exc

    table = Table(title="Fetched official India batch")
    table.add_column("Ticker", style="cyan")
    table.add_column("Status", style="magenta")
    table.add_column("Details", style="green")
    for item in result.completed:
        summary = ", ".join(f"{kind}:{item.row_counts.get(kind, 0)}" for kind in item.imported_kinds)
        table.add_row(item.ticker, "ok", summary)
    for ticker, error in result.failed:
        table.add_row(ticker, "failed", error)
    console.print(table)
    logger.info(
        f"Fetched official India batch: {len(result.completed)} succeeded, "
        f"{len(result.failed)} failed"
    )


if __name__ == "__main__":
    app()
