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
from typing import Optional

import typer
from loguru import logger
from rich.console import Console
from rich.table import Table
from sqlalchemy import inspect

from pipeline.db import init_db
from pipeline.db.base import get_engine
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


if __name__ == "__main__":
    app()
