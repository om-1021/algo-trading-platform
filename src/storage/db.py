"""DuckDB connection + schema initialization.

Single DuckDB file holds everything. Tables are namespaced by lane:
  - Shared market data: market_bars_daily, market_bars_1m, instruments
  - Swing lane:    swing_signals,    swing_trades,    swing_strategy_runs
  - Intraday lane: intraday_signals, intraday_trades, intraday_strategy_runs
  - Agent logs:    agent_decisions   (carries a 'lane' column for filtering)

We never JOIN swing tables with intraday tables. They are independent worlds
that happen to share the same DB file for operational convenience.
"""
from __future__ import annotations

from pathlib import Path

import duckdb
from loguru import logger

# Absolute import — works when imported as part of the `src` package.
from config import settings

_SCHEMA_FILE = Path(__file__).parent / "schema.sql"


def get_conn() -> duckdb.DuckDBPyConnection:
    """Open a connection to the DuckDB file. Caller closes."""
    return duckdb.connect(str(settings.db_path))


def init_schema() -> None:
    """Create all tables if they don't exist. Idempotent."""
    sql = _SCHEMA_FILE.read_text(encoding="utf-8")
    with get_conn() as conn:
        conn.execute(sql)
    logger.info("Schema initialized at {}", settings.db_path)
