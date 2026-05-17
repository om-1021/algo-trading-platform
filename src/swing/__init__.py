"""SWING LANE — daily-bar strategies, overnight holds, EOD decisions.

Strict invariant: NOTHING in this package may import from src.intraday,
and nothing in src.intraday may import from here. The two lanes are
independent worlds that only share market data tables.
"""
from .base import SwingSignal, SwingStrategy

__all__ = ["SwingSignal", "SwingStrategy"]
