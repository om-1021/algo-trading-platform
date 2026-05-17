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

import json
import statistics
import uuid
from datetime import date
from typing import Iterator

from loguru import logger

from src.storage import get_conn
from src.swing.backtest import _backtest_window
from src.swing.strategies import EmaCrossover

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


def rolling_folds(
    trading_days: list[date],
    train_days: int,
    test_days: int,
    step_days: int,
) -> Iterator[tuple[date, date, date, date]]:
    """Slide a (train_days + test_days) window over the trading-day list.

    Args:
        trading_days: ordered unique list of trading dates available in the
            data. Walk-forward operates on these indices, NOT calendar days.
        train_days: number of trading days in the train window
        test_days: number of trading days in the test window
        step_days: number of trading days to advance between folds.
            Use step_days = test_days for non-overlapping test windows.

    Yields:
        (train_start, train_end, test_start, test_end) tuples, all inclusive.

    A fold at index i uses trading_days[i : i + train_days + test_days].
    The last yielded fold satisfies i + train_days + test_days <= len(trading_days).
    """
    fold_len = train_days + test_days
    n = len(trading_days)
    if fold_len > n:
        return
    i = 0
    while i + fold_len <= n:
        train_start = trading_days[i]
        train_end = trading_days[i + train_days - 1]
        test_start = trading_days[i + train_days]
        test_end = trading_days[i + fold_len - 1]
        yield (train_start, train_end, test_start, test_end)
        i += step_days


def _history_trading_days(instrument_keys: list[str]) -> list[date]:
    """Sorted unique trading days present in market_bars_daily for the universe."""
    with get_conn() as conn:
        placeholders = ",".join(["?"] * len(instrument_keys))
        rows = conn.execute(
            f"""
            SELECT DISTINCT bar_date
            FROM market_bars_daily
            WHERE instrument_key IN ({placeholders})
            ORDER BY bar_date
            """,
            instrument_keys,
        ).fetchall()
    return [r[0] for r in rows]


def _insert_wfo_run(
    wfo_id: str, strategy_name: str, grid: list[tuple[int, int]],
    train_days: int, test_days: int, step_days: int,
    metric_name: str, baseline: tuple[int, int],
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO swing_walkforward_runs
              (wfo_id, strategy_name, param_grid_json,
               train_window_days, test_window_days, step_days,
               selection_metric, baseline_params_json, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'running')
            """,
            [
                wfo_id, strategy_name, json.dumps([list(p) for p in grid]),
                train_days, test_days, step_days,
                metric_name,
                json.dumps({"fast": baseline[0], "slow": baseline[1]}),
            ],
        )


def _mark_wfo_complete(wfo_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE swing_walkforward_runs SET status = 'complete' WHERE wfo_id = ?",
            [wfo_id],
        )


def _mark_wfo_failed(wfo_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE swing_walkforward_runs SET status = 'failed' WHERE wfo_id = ?",
            [wfo_id],
        )


def _insert_fold(
    wfo_id: str, fold_index: int,
    train_start: date, train_end: date, test_start: date, test_end: date,
    role: str, chosen_params: tuple[int, int],
    train_score: float | None, test_run_id: str, test_summary: dict,
) -> None:
    # test_summary may contain a trades_list — strip it before serialising.
    summary_for_json = {k: v for k, v in test_summary.items() if k != "trades_list"}
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO swing_walkforward_folds
              (fold_id, wfo_id, fold_index,
               train_start, train_end, test_start, test_end,
               role, chosen_params_json, train_selection_score,
               test_run_id, test_summary_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                str(uuid.uuid4()), wfo_id, fold_index,
                train_start, train_end, test_start, test_end,
                role, json.dumps({"fast": chosen_params[0], "slow": chosen_params[1]}),
                train_score, test_run_id, json.dumps(summary_for_json),
            ],
        )


def _log_skipped_fold(fold_index: int, train_start: date, train_end: date) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO data_health_events (event_id, severity, component, message)
            VALUES (?, 'warn', 'walkforward',
                    'fold ' || ? || ' skipped: entire grid disqualified on train window '
                    || ? || '..' || ?)
            """,
            [str(uuid.uuid4()), fold_index, train_start, train_end],
        )


def run_walkforward(
    instrument_keys: list[str],
    grid: list[tuple[int, int]] | None = None,
    train_window_days: int = 252,
    test_window_days: int = 63,
    step_days: int = 63,
    baseline_params: tuple[int, int] = (20, 50),
) -> str:
    """Run a walk-forward study over the universe.

    Returns the wfo_id. All trades and fold records persist; train trades do not.
    """
    if grid is None:
        grid = generate_grid()
    if not instrument_keys:
        raise ValueError("instrument_keys must not be empty")

    wfo_id = str(uuid.uuid4())
    # v1: only one selection metric exists; make this a parameter when more are added.
    _insert_wfo_run(
        wfo_id, EmaCrossover.name, grid,
        train_window_days, test_window_days, step_days,
        "sharpe_per_trade", baseline_params,
    )
    logger.info(
        "WFO {} started: {} symbols, {} grid combos, train={}d test={}d step={}d",
        wfo_id, len(instrument_keys), len(grid),
        train_window_days, test_window_days, step_days,
    )

    trading_days = _history_trading_days(instrument_keys)
    folds = list(rolling_folds(
        trading_days, train_window_days, test_window_days, step_days,
    ))
    logger.info("WFO will run {} folds", len(folds))

    try:
        for i, (train_start, train_end, test_start, test_end) in enumerate(folds):
            logger.info(
                "Fold {}: train {}..{}  test {}..{}",
                i, train_start, train_end, test_start, test_end,
            )

            # --- Grid scoring on train window (in-memory only) ---
            scored: list[tuple[tuple[int, int], float | None]] = []
            for fast, slow in grid:
                strat = EmaCrossover(fast=fast, slow=slow)
                summary = _backtest_window(
                    strat, instrument_keys,
                    from_date=train_start, to_date=train_end,
                    persist=False,
                )
                score = sharpe_per_trade(summary["trades_list"])
                scored.append(((fast, slow), score))

            # --- Pick the winner; skip fold if entire grid is disqualified ---
            valid = [(p, s) for p, s in scored if s is not None]
            if not valid:
                logger.warning("Fold {}: no valid grid combo; skipping fold", i)
                _log_skipped_fold(i, train_start, train_end)
                continue
            # Best by score; tie-break by smallest (fast + slow).
            valid.sort(key=lambda x: (-x[1], x[0][0] + x[0][1]))
            winner_params, winner_score = valid[0]
            logger.info(
                "Fold {}: winner {} score={:.4f}",
                i, winner_params, winner_score,
            )

            # --- Optimized test run (persisted) ---
            opt_strat = EmaCrossover(fast=winner_params[0], slow=winner_params[1])
            opt_summary = _backtest_window(
                opt_strat, instrument_keys,
                from_date=test_start, to_date=test_end,
                persist=True,
            )
            opt_summary["sharpe_per_trade"] = sharpe_per_trade(opt_summary["trades_list"])
            _insert_fold(
                wfo_id, i, train_start, train_end, test_start, test_end,
                role="optimized",
                chosen_params=winner_params, train_score=winner_score,
                test_run_id=opt_summary["run_id"], test_summary=opt_summary,
            )

            # --- Baseline test run (persisted) ---
            base_strat = EmaCrossover(fast=baseline_params[0], slow=baseline_params[1])
            base_summary = _backtest_window(
                base_strat, instrument_keys,
                from_date=test_start, to_date=test_end,
                persist=True,
            )
            base_summary["sharpe_per_trade"] = sharpe_per_trade(base_summary["trades_list"])
            _insert_fold(
                wfo_id, i, train_start, train_end, test_start, test_end,
                role="baseline",
                chosen_params=baseline_params, train_score=None,
                test_run_id=base_summary["run_id"], test_summary=base_summary,
            )

        _mark_wfo_complete(wfo_id)
        logger.success("WFO {} complete", wfo_id)
    except Exception:
        _mark_wfo_failed(wfo_id)
        logger.exception("WFO {} failed", wfo_id)
        raise

    return wfo_id
