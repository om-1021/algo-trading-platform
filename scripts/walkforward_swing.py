"""Run a walk-forward study for the EMA crossover swing strategy.

Reads whatever instrument_keys exist in market_bars_daily, runs the WFO
loop defined in src/swing/walkforward.py, prints a per-fold table plus
aggregate out-of-sample stats and a per-symbol breakdown (for the
optimized role).

Prereqs: run scripts/init_db.py and scripts/backfill_daily.py first.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows console defaults to cp1252 which can't encode ₹ / em-dash etc.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from loguru import logger

from src.storage import get_conn, init_schema
from src.swing.walkforward import run_walkforward


def _universe_from_db() -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT instrument_key
            FROM market_bars_daily
            ORDER BY instrument_key
            """,
        ).fetchall()
    return [r[0] for r in rows]


def _print_fold_table(wfo_id: str) -> None:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT fold_index, train_start, train_end, test_start, test_end,
                   role, chosen_params_json, train_selection_score,
                   test_summary_json
            FROM swing_walkforward_folds
            WHERE wfo_id = ?
            ORDER BY fold_index, role
            """,
            [wfo_id],
        ).fetchall()
    if not rows:
        print("\n(no folds — entire grid may have been disqualified per fold)")
        return

    # Group rows by fold_index for side-by-side display.
    by_fold: dict[int, dict[str, tuple]] = {}
    for r in rows:
        fold_idx = r[0]
        role = r[5]
        by_fold.setdefault(fold_idx, {})[role] = r

    print("\nPer-fold out-of-sample:")
    print(
        f"  {'Fold':>4}  {'Train range':<24}  {'Test range':<24}  "
        f"{'Optimized':<22}  {'Test net P&L':>14}  {'Baseline':<10}  {'Test net P&L':>14}"
    )
    print(f"  {'-' * 4}  {'-' * 24}  {'-' * 24}  {'-' * 22}  {'-' * 14}  {'-' * 10}  {'-' * 14}")
    for fold_idx in sorted(by_fold):
        f_rows = by_fold[fold_idx]
        opt = f_rows.get("optimized")
        bas = f_rows.get("baseline")
        if opt is None:
            continue
        train_range = f"{opt[1]}..{opt[2]}"
        test_range = f"{opt[3]}..{opt[4]}"
        opt_params = json.loads(opt[6])
        opt_summary = json.loads(opt[8])
        opt_str = f"({opt_params['fast']}, {opt_params['slow']}) score={opt[7]:.2f}"
        opt_pnl = opt_summary.get("total_net_pnl", 0.0)
        if bas is None:
            bas_str = "(none)"
            bas_pnl = 0.0
        else:
            bas_params = json.loads(bas[6])
            bas_summary = json.loads(bas[8])
            bas_str = f"({bas_params['fast']}, {bas_params['slow']})"
            bas_pnl = bas_summary.get("total_net_pnl", 0.0)
        print(
            f"  {fold_idx:>4}  {train_range:<24}  {test_range:<24}  "
            f"{opt_str:<22}  ₹{opt_pnl:>12,.2f}  {bas_str:<10}  ₹{bas_pnl:>12,.2f}"
        )


def _print_aggregate(wfo_id: str) -> None:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT f.role,
                   COUNT(t.trade_id)                AS trades,
                   ROUND(SUM(t.net_pnl), 2)          AS total_net,
                   ROUND(AVG(CASE WHEN t.net_pnl > 0 THEN 1.0 ELSE 0.0 END), 4) AS win_rate
            FROM swing_walkforward_folds f
            JOIN swing_trades t ON t.run_id = f.test_run_id
            WHERE f.wfo_id = ?
            GROUP BY f.role
            ORDER BY f.role
            """,
            [wfo_id],
        ).fetchall()
    if not rows:
        return
    print("\nAggregate out-of-sample:")
    for role, n, total, wr in rows:
        print(f"  {role:<10} {n:>4} trades   total ₹{total:>12,.2f}   win-rate {wr:.4f}")


def _print_per_symbol(wfo_id: str, role: str = "optimized") -> None:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT i.tradingsymbol,
                   COUNT(t.trade_id)                  AS trades,
                   ROUND(SUM(t.net_pnl), 2)            AS net_pnl,
                   ROUND(AVG(t.net_pnl), 2)            AS avg_pnl
            FROM swing_walkforward_folds f
            JOIN swing_trades t ON t.run_id = f.test_run_id
            JOIN instruments  i USING (instrument_key)
            WHERE f.wfo_id = ? AND f.role = ?
            GROUP BY i.tradingsymbol
            ORDER BY net_pnl DESC NULLS LAST
            """,
            [wfo_id, role],
        ).fetchall()
    if not rows:
        return
    print(f"\nPer-symbol out-of-sample ({role} role):")
    print(f"  {'Symbol':<14} {'Trades':>7} {'Net P&L':>14} {'Avg/Trade':>14}")
    print(f"  {'-' * 14} {'-' * 7} {'-' * 14} {'-' * 14}")
    for sym, n, pnl, avg in rows:
        pnl_str = f"₹{pnl:>10,.2f}" if pnl is not None else "—"
        avg_str = f"₹{avg:>10,.2f}" if avg is not None else "—"
        print(f"  {sym:<14} {n:>7} {pnl_str:>14} {avg_str:>14}")


def main() -> None:
    init_schema()
    keys = _universe_from_db()
    if not keys:
        logger.error("No instruments in market_bars_daily. Run scripts/backfill_daily.py first.")
        sys.exit(1)

    wfo_id = run_walkforward(instrument_keys=keys)

    print(f"\nWalk-forward complete: wfo_id={wfo_id}")
    _print_fold_table(wfo_id)
    _print_aggregate(wfo_id)
    _print_per_symbol(wfo_id, role="optimized")


if __name__ == "__main__":
    main()
