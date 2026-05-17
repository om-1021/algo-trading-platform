"""INTRADAY LANE — minute-bar strategies, EOD square-off, no overnight risk.

Strict invariant: NOTHING in this package may import from src.swing,
and nothing in src.swing may import from here. The two lanes are
independent worlds that only share market data tables.
"""
