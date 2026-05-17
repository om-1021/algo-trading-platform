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

FAST_PERIODS: tuple[int, ...] = (5, 8, 10, 13, 15, 20, 25)
SLOW_PERIODS: tuple[int, ...] = (30, 40, 50, 60, 100, 200)


def generate_grid() -> list[tuple[int, int]]:
    """Coarse EMA grid: 7 × 6 = 42 raw combos, filtered to fast < slow."""
    return [(f, s) for f in FAST_PERIODS for s in SLOW_PERIODS if f < s]
