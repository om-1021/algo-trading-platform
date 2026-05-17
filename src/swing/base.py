"""Base classes for swing-lane strategies.

A SwingStrategy consumes daily bars for a single instrument and emits
SwingSignals. It is stateless across instruments — call it once per symbol.

The strategy never persists anything itself; the backtest/live runner is
responsible for writing signals and trades to the database.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd


@dataclass
class SwingSignal:
    """One swing-lane decision.

    Direction semantics:
      "LONG" — open a long position at entry_price
      "EXIT" — close any open long position at entry_price (reused as exit price)
    Shorts are intentionally not in scope for phase 1.
    """
    instrument_key: str
    signal_ts: datetime              # tz-aware datetime, market close of the bar
    direction: str                   # "LONG" | "EXIT"
    entry_price: float | None = None
    stop_loss: float | None = None
    target: float | None = None
    reasoning: dict[str, Any] = field(default_factory=dict)


class SwingStrategy(ABC):
    """Abstract swing strategy. Subclasses set `name` and `version`."""
    name: str = "base"
    version: str = "0"

    @abstractmethod
    def generate_signals(
        self,
        bars: pd.DataFrame,
        instrument_key: str,
    ) -> list[SwingSignal]:
        """Given a DataFrame of daily bars (indexed by date, columns:
        open, high, low, close, volume), return signals in chronological order."""
        ...

    def params(self) -> dict[str, Any]:
        """Frozen parameter snapshot for the run log. Override in subclasses."""
        return {}
