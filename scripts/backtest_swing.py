"""Backtest the EMA 20/50 crossover on whatever daily bars are in DuckDB.

Prereq: run scripts/backfill_daily.py first to populate market_bars_daily.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows console defaults to cp1252 which can't encode ₹ / em-dash etc.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from loguru import logger

from src.storage import get_conn, init_schema
from src.swing.backtest import run_backtest
from src.swing.strategies import EmaCrossover


def main() -> None:
    init_schema()

    with get_conn() as conn:
        rows = conn.execute("""
            SELECT DISTINCT instrument_key
            FROM market_bars_daily
            ORDER BY instrument_key
        """).fetchall()
    keys = [r[0] for r in rows]
    if not keys:
        logger.error("No daily bars in DB. Run scripts/backfill_daily.py first.")
        sys.exit(1)

    logger.info("Backtesting EMA 20/50 on {} instruments", len(keys))
    strategy = EmaCrossover(fast=20, slow=50)
    summary = run_backtest(strategy, keys)

    # Per-symbol breakdown
    with get_conn() as conn:
        breakdown = conn.execute("""
            SELECT i.tradingsymbol,
                   COUNT(t.trade_id)                    AS trades,
                   ROUND(SUM(t.net_pnl), 2)             AS net_pnl,
                   ROUND(AVG(t.net_pnl), 2)             AS avg_pnl
            FROM swing_trades t
            JOIN instruments i USING (instrument_key)
            WHERE t.run_id = ?
            GROUP BY i.tradingsymbol
            ORDER BY net_pnl DESC NULLS LAST
        """, [summary["run_id"]]).fetchall()

    print("\nPer-symbol breakdown:")
    print(f"  {'Symbol':<14} {'Trades':>7} {'Net P&L':>12} {'Avg/Trade':>12}")
    print(f"  {'-' * 14} {'-' * 7} {'-' * 12} {'-' * 12}")
    for sym, n, pnl, avg in breakdown:
        pnl_str = f"₹{pnl:>10.2f}" if pnl is not None else "—"
        avg_str = f"₹{avg:>10.2f}" if avg is not None else "—"
        print(f"  {sym:<14} {n:>7} {pnl_str:>12} {avg_str:>12}")


if __name__ == "__main__":
    main()
