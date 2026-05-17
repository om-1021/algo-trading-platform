"""Walk-forward validation harness for the swing lane.

See docs/superpowers/specs/2026-05-17-walkforward-swing-design.md for the
design rationale. This module exposes:

  generate_grid()        — the ~30 valid (fast, slow) EMA pairs we search
  sharpe_per_trade(...)  — selection metric: mean(net_pnl) / stdev(net_pnl)
  rolling_folds(...)     — yields (train_start, train_end, test_start, test_end)
  run_walkforward(...)   — the orchestrator; returns wfo_id

Strategy-centricity invariants: see spec §1.5. Trades from grid scoring are
in-memory only (persist=False); only test-window trades land in swing_trades.
"""
from __future__ import annotations

import statistics

FAST_PERIODS: tuple[int, ...] = (5, 8, 10, 13, 15, 20, 25)
SLOW_PERIODS: tuple[int, ...] = (30, 40, 50, 60, 100, 200)


def generate_grid() -> list[tuple[int, int]]:
    """Coarse EMA grid: 7 × 6 = 42 raw combos, filtered to fast < slow."""
    return [(f, s) for f in FAST_PERIODS for s in SLOW_PERIODS if f < s]


def sharpe_per_trade(trades: list[dict]) -> float | None:
    """Selection metric: mean(net_pnl) / stdev(net_pnl) across a flat list of trades.

    Returns None when the metric is undefined:
      - empty list
      - single trade (stdev undefined)
      - all trades have identical net_pnl (stdev == 0)

    Trades are expected to be the dicts produced by _pair_signals_into_trades
    in src/swing/backtest.py — i.e. each has a 'net_pnl' float key.
    """
    if len(trades) < 2:
        return None
    pnls = [t["net_pnl"] for t in trades]
    mean = statistics.mean(pnls)
    stdev = statistics.stdev(pnls)
    if stdev == 0:
        return None
    return mean / stdev
