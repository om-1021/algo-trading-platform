"""Swing backtest runner.

Walks a strategy over historical daily bars in DuckDB, persists every
signal and every paired trade into swing_signals / swing_trades, and
returns a summary dict.

Cost model: realistic NSE delivery (cash equity, T+1 settlement).
  - Brokerage:       Upstox ₹20 flat per executed order (we ignore the
                     0.05% alt cap since it's higher for small notionals)
  - STT:             0.1% on each leg (delivery)
  - Exchange charges: 0.00322% per leg
  - GST:             18% on brokerage + exchange charges
  - SEBI charges:    negligible at retail scale
  - Stamp duty:      0.015% on buy leg only (delivery)
  - DP charges:      ~₹18 on sell leg
This works out to roughly 0.075–0.08% per leg on typical retail trade
sizes. We use 7.5 bps per leg as a clean approximation. You can override
it with cost_bps_per_leg= kwarg.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

import pandas as pd
from loguru import logger

from src.storage import get_conn
from src.swing.base import SwingSignal, SwingStrategy

DEFAULT_COST_BPS_PER_LEG = 7.5    # 0.075% — see docstring
DEFAULT_CAPITAL_PER_TRADE = 10_000.0  # ₹ per position


def _load_bars(instrument_key: str) -> pd.DataFrame:
    with get_conn() as conn:
        df = conn.execute(
            """
            SELECT bar_date, open, high, low, close, volume
            FROM market_bars_daily
            WHERE instrument_key = ?
            ORDER BY bar_date
            """,
            [instrument_key],
        ).fetchdf()
    if df.empty:
        return df
    df["bar_date"] = pd.to_datetime(df["bar_date"])
    return df.set_index("bar_date")


def _create_run(strategy: SwingStrategy) -> str:
    run_id = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO swing_strategy_runs
              (run_id, strategy_name, strategy_version, params_json, status)
            VALUES (?, ?, ?, ?, 'active')
            """,
            [run_id, strategy.name, strategy.version, json.dumps(strategy.params())],
        )
    return run_id


def _persist_signals(
    run_id: str,
    signals: list[SwingSignal],
) -> dict[tuple[str, datetime], str]:
    """Insert signals; return mapping (instrument_key, signal_ts) → signal_id."""
    mapping: dict[tuple[str, datetime], str] = {}
    rows = []
    for s in signals:
        sid = str(uuid.uuid4())
        mapping[(s.instrument_key, s.signal_ts)] = sid
        rows.append([
            sid, run_id, s.instrument_key, s.signal_ts, s.direction,
            s.entry_price, s.stop_loss, s.target,
            json.dumps(s.reasoning), True,
        ])
    if rows:
        with get_conn() as conn:
            conn.executemany(
                """
                INSERT INTO swing_signals
                  (signal_id, run_id, instrument_key, signal_ts, direction,
                   entry_price, stop_loss, target, reasoning_json, taken)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
    return mapping


def _pair_signals_into_trades(
    run_id: str,
    signals: list[SwingSignal],
    sig_id_map: dict[tuple[str, datetime], str],
    cost_bps_per_leg: float,
    capital_per_trade: float,
) -> list[dict]:
    """Walk per-symbol signals chronologically; pair LONG→EXIT into trades."""
    per_symbol: dict[str, list[SwingSignal]] = {}
    for s in signals:
        per_symbol.setdefault(s.instrument_key, []).append(s)

    trades: list[dict] = []
    for key, sigs in per_symbol.items():
        sigs.sort(key=lambda s: s.signal_ts)
        open_sig: SwingSignal | None = None
        for s in sigs:
            if s.direction == "LONG" and open_sig is None:
                open_sig = s
            elif s.direction == "EXIT" and open_sig is not None:
                entry = open_sig.entry_price or 0.0
                exit_ = s.entry_price or 0.0
                qty = int(capital_per_trade // entry) if entry > 0 else 0
                if qty == 0:
                    open_sig = None
                    continue
                gross = (exit_ - entry) * qty
                cost = (entry * qty + exit_ * qty) * (cost_bps_per_leg / 10_000.0)
                trades.append({
                    "trade_id": str(uuid.uuid4()),
                    "entry_signal_id": sig_id_map[(open_sig.instrument_key, open_sig.signal_ts)],
                    "exit_signal_id": sig_id_map[(s.instrument_key, s.signal_ts)],
                    "run_id": run_id,
                    "instrument_key": key,
                    "direction": "LONG",
                    "qty": qty,
                    "entry_ts": open_sig.signal_ts,
                    "entry_price": entry,
                    "exit_ts": s.signal_ts,
                    "exit_price": exit_,
                    "exit_reason": "signal",
                    "gross_pnl": gross,
                    "cost_estimate": cost,
                    "net_pnl": gross - cost,
                    "status": "closed",
                })
                open_sig = None
        # Unclosed positions at end of history are intentionally dropped from
        # backtest results. Live runner will treat them differently (carry forward).
    return trades


def _persist_trades(trades: list[dict]) -> None:
    if not trades:
        return
    rows = [[
        t["trade_id"], t["entry_signal_id"], t["exit_signal_id"], t["run_id"],
        t["instrument_key"], t["direction"], t["qty"],
        t["entry_ts"], t["entry_price"],
        t["exit_ts"], t["exit_price"], t["exit_reason"],
        t["gross_pnl"], t["cost_estimate"], t["net_pnl"], t["status"],
    ] for t in trades]
    with get_conn() as conn:
        conn.executemany(
            """
            INSERT INTO swing_trades
              (trade_id, entry_signal_id, exit_signal_id, run_id,
               instrument_key, direction, qty,
               entry_ts, entry_price, exit_ts, exit_price, exit_reason,
               gross_pnl, cost_estimate, net_pnl, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )


def _summary(trades: list[dict], run_id: str) -> dict[str, Any]:
    if not trades:
        return {"run_id": run_id, "trades": 0}
    pnls = [t["net_pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    return {
        "run_id": run_id,
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(pnls) - len(wins),
        "win_rate": round(len(wins) / len(trades), 4),
        "total_net_pnl": round(sum(pnls), 2),
        "avg_trade_pnl": round(sum(pnls) / len(pnls), 2),
        "best_trade": round(max(pnls), 2),
        "worst_trade": round(min(pnls), 2),
    }


def run_backtest(
    strategy: SwingStrategy,
    instrument_keys: list[str],
    cost_bps_per_leg: float = DEFAULT_COST_BPS_PER_LEG,
    capital_per_trade: float = DEFAULT_CAPITAL_PER_TRADE,
) -> dict[str, Any]:
    """Run strategy over given universe, persist everything, return summary."""
    run_id = _create_run(strategy)
    logger.info("Run {} started — {} v{}", run_id, strategy.name, strategy.version)

    all_signals: list[SwingSignal] = []
    for key in instrument_keys:
        bars = _load_bars(key)
        if bars.empty:
            logger.warning("No bars for {}", key)
            continue
        sigs = strategy.generate_signals(bars, key)
        if sigs:
            logger.debug("  {} → {} signals", key, len(sigs))
        all_signals.extend(sigs)

    sig_id_map = _persist_signals(run_id, all_signals)
    trades = _pair_signals_into_trades(
        run_id, all_signals, sig_id_map, cost_bps_per_leg, capital_per_trade,
    )
    _persist_trades(trades)
    summary = _summary(trades, run_id)
    logger.success("Backtest complete: {}", summary)
    return summary
