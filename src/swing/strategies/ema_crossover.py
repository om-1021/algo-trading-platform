"""EMA crossover — classic trend-following baseline.

Rules:
  - LONG when fast EMA crosses above slow EMA
  - EXIT when fast EMA crosses below slow EMA
  - Long-only (no shorts), no profit target, no stop loss
  - Always-in-or-out (no scaling, no pyramiding)

Purpose: validate the pipeline. This is a known-mediocre strategy that
loses in choppy markets and makes money in trending ones. If our
infrastructure produces sensible-looking signals and trades from this,
the foundation is sound. Better strategies come later.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from src.swing.base import SwingSignal, SwingStrategy

IST = ZoneInfo("Asia/Kolkata")


class EmaCrossover(SwingStrategy):
    name = "ema_crossover"
    version = "1.0"

    def __init__(self, fast: int = 20, slow: int = 50) -> None:
        if fast >= slow:
            raise ValueError("fast EMA period must be less than slow")
        self.fast = fast
        self.slow = slow

    def params(self) -> dict[str, Any]:
        return {"fast": self.fast, "slow": self.slow}

    def generate_signals(
        self,
        bars: pd.DataFrame,
        instrument_key: str,
    ) -> list[SwingSignal]:
        if len(bars) < self.slow + 1:
            return []

        df = bars.copy()
        df["ema_fast"] = df["close"].ewm(span=self.fast, adjust=False).mean()
        df["ema_slow"] = df["close"].ewm(span=self.slow, adjust=False).mean()
        df["diff"] = df["ema_fast"] - df["ema_slow"]
        df["prev_diff"] = df["diff"].shift(1)

        signals: list[SwingSignal] = []
        in_position = False
        for ts, row in df.dropna(subset=["prev_diff"]).iterrows():
            signal_ts = self._to_ist_close(ts)
            crossed_up = row["prev_diff"] < 0 <= row["diff"]
            crossed_down = row["prev_diff"] > 0 >= row["diff"]

            if not in_position and crossed_up:
                signals.append(SwingSignal(
                    instrument_key=instrument_key,
                    signal_ts=signal_ts,
                    direction="LONG",
                    entry_price=float(row["close"]),
                    reasoning={
                        "trigger": "ema_fast_crossed_above_ema_slow",
                        "ema_fast": float(row["ema_fast"]),
                        "ema_slow": float(row["ema_slow"]),
                        "fast_period": self.fast,
                        "slow_period": self.slow,
                    },
                ))
                in_position = True
            elif in_position and crossed_down:
                signals.append(SwingSignal(
                    instrument_key=instrument_key,
                    signal_ts=signal_ts,
                    direction="EXIT",
                    entry_price=float(row["close"]),
                    reasoning={
                        "trigger": "ema_fast_crossed_below_ema_slow",
                        "ema_fast": float(row["ema_fast"]),
                        "ema_slow": float(row["ema_slow"]),
                    },
                ))
                in_position = False
        return signals

    @staticmethod
    def _to_ist_close(ts) -> datetime:
        """Convert a pandas Timestamp / datetime to NSE close (15:30 IST)."""
        if isinstance(ts, pd.Timestamp):
            ts = ts.to_pydatetime()
        # Drop any existing tz, set to 15:30 IST.
        ts = ts.replace(hour=15, minute=30, second=0, microsecond=0, tzinfo=None)
        return ts.replace(tzinfo=IST)
