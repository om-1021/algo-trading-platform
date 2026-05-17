"""Smoke test: insert synthetic daily bars, run EMA crossover backtest,
verify signals and trades land in the DB. No Upstox calls needed."""
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.storage import get_conn, init_schema
from src.swing.backtest import run_backtest
from src.swing.strategies import EmaCrossover


def _make_synthetic(seed: int, n_days: int = 600, drift: float = 0.0005,
                    vol: float = 0.018, start_price: float = 1000.0) -> pd.DataFrame:
    """Geometric Brownian motion → realistic-looking OHLCV bars."""
    rng = np.random.default_rng(seed)
    log_rets = rng.normal(drift, vol, n_days)
    close = start_price * np.exp(np.cumsum(log_rets))
    # Open = previous close (with small overnight gap), high/low around close.
    open_ = np.concatenate([[start_price], close[:-1]]) * (1 + rng.normal(0, 0.002, n_days))
    rng2 = rng.uniform(0, 0.012, n_days)
    high = np.maximum(open_, close) * (1 + rng2)
    low = np.minimum(open_, close) * (1 - rng2)
    volume = rng.integers(500_000, 5_000_000, n_days)
    dates = pd.bdate_range(end=date.today(), periods=n_days)
    return pd.DataFrame({
        "bar_date": dates.date,
        "open": open_, "high": high, "low": low, "close": close, "volume": volume,
        "open_interest": 0,
    })


def main():
    init_schema()

    # Three synthetic instruments: trending up, sideways, trending down.
    universe = [
        ("NSE_EQ|FAKE001", "TRENDUP",   {"drift": 0.0010, "vol": 0.015}),
        ("NSE_EQ|FAKE002", "SIDEWAYS",  {"drift": 0.0000, "vol": 0.020}),
        ("NSE_EQ|FAKE003", "TRENDDOWN", {"drift": -0.0008, "vol": 0.016}),
    ]

    with get_conn() as conn:
        # Clean any prior smoke-test rows
        conn.execute("DELETE FROM market_bars_daily WHERE instrument_key LIKE 'NSE_EQ|FAKE%'")
        conn.execute("DELETE FROM instruments WHERE instrument_key LIKE 'NSE_EQ|FAKE%'")

        for i, (key, sym, kwargs) in enumerate(universe):
            conn.execute("""
                INSERT INTO instruments
                  (instrument_key, exchange, segment, tradingsymbol, name, instrument_type)
                VALUES (?, 'NSE', 'NSE_EQ', ?, ?, 'EQ')
            """, [key, sym, sym])
            df = _make_synthetic(seed=i + 1, **kwargs)
            rows = df[["bar_date", "open", "high", "low", "close", "volume", "open_interest"]].values.tolist()
            for r in rows:
                conn.execute("""
                    INSERT INTO market_bars_daily
                      (instrument_key, bar_date, open, high, low, close, volume, open_interest)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, [key, *r])
            print(f"  Inserted {len(rows)} synthetic bars for {sym}")

    # Run backtest
    keys = [k for k, _, _ in universe]
    summary = run_backtest(EmaCrossover(fast=20, slow=50), keys)
    print(f"\nSummary: {summary}")

    # Verify what landed
    with get_conn() as conn:
        n_runs = conn.execute("SELECT COUNT(*) FROM swing_strategy_runs").fetchone()[0]
        n_sigs = conn.execute("SELECT COUNT(*) FROM swing_signals WHERE run_id = ?",
                              [summary["run_id"]]).fetchone()[0]
        n_trades = conn.execute("SELECT COUNT(*) FROM swing_trades WHERE run_id = ?",
                                [summary["run_id"]]).fetchone()[0]
        per_sym = conn.execute("""
            SELECT i.tradingsymbol, COUNT(t.trade_id), ROUND(SUM(t.net_pnl), 2)
            FROM swing_trades t JOIN instruments i USING (instrument_key)
            WHERE t.run_id = ? GROUP BY i.tradingsymbol ORDER BY 1
        """, [summary["run_id"]]).fetchall()

    print(f"\nDB verification:")
    print(f"  runs in DB:         {n_runs}")
    print(f"  signals this run:   {n_sigs}")
    print(f"  trades this run:    {n_trades}")
    print(f"\nPer-symbol P&L:")
    for sym, n, pnl in per_sym:
        print(f"  {sym:<12} {n:>3} trades   ₹{pnl}")

    # Sanity: trending-up should have net positive P&L more often than not.
    assert n_runs >= 1
    assert n_sigs > 0, "Expected some signals"
    assert n_trades > 0, "Expected some closed trades"
    print("\n✓ All assertions passed")


if __name__ == "__main__":
    main()
