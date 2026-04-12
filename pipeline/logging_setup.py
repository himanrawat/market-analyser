"""Loguru-based logging. Imported once at process entry."""
from __future__ import annotations

import sys

from loguru import logger

from pipeline.config import settings


def configure_logging() -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    )
    logger.add(
        settings.log_dir / "pipeline_{time:YYYY-MM-DD}.log",
        level=settings.log_level,
        rotation="1 day",
        retention="30 days",
        compression="zip",
        enqueue=True,
    )
