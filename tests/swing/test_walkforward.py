"""Unit tests for src/swing/walkforward.py. Plain assert-based, runnable as
a script. Add new test_* functions and they auto-run from main().
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.swing.walkforward import generate_grid, sharpe_per_trade


def test_generate_grid_returns_only_valid_pairs():
    grid = generate_grid()
    # Every pair must have fast < slow.
    for fast, slow in grid:
        assert fast < slow, f"invalid pair (fast={fast}, slow={slow})"


def test_generate_grid_uses_documented_values():
    grid = generate_grid()
    pairs = set(grid)
    # A few sentinel pairs we MUST have (canonical EMA pairs from the spec).
    assert (20, 50) in pairs, "missing canonical (20, 50)"
    assert (5, 30) in pairs, "missing (5, 30)"
    assert (25, 200) in pairs, "missing (25, 200)"


def test_generate_grid_excludes_invalid_pairs():
    grid = generate_grid()
    pairs = set(grid)
    # fast >= slow should never appear.
    assert (50, 50) not in pairs
    assert (60, 50) not in pairs


def test_generate_grid_size_in_range():
    grid = generate_grid()
    # Spec says "~30 valid pairs". 7 fast × 6 slow (all fast < all slow) = 42.
    assert 25 <= len(grid) <= 50, f"unexpected grid size {len(grid)}"


def test_sharpe_per_trade_basic():
    # Three trades, mean 100, stdev > 0 → finite score
    trades = [
        {"net_pnl": 100.0},
        {"net_pnl": 200.0},
        {"net_pnl": 50.0},
    ]
    score = sharpe_per_trade(trades)
    assert score is not None
    assert score > 0, f"positive mean should give positive score, got {score}"


def test_sharpe_per_trade_zero_trades_returns_none():
    assert sharpe_per_trade([]) is None


def test_sharpe_per_trade_one_trade_returns_none():
    # Stdev is undefined for n=1; we disqualify.
    assert sharpe_per_trade([{"net_pnl": 100.0}]) is None


def test_sharpe_per_trade_zero_stdev_returns_none():
    # All identical → stdev = 0 → undefined ratio.
    trades = [{"net_pnl": 100.0}, {"net_pnl": 100.0}, {"net_pnl": 100.0}]
    assert sharpe_per_trade(trades) is None


def test_sharpe_per_trade_negative_mean():
    trades = [
        {"net_pnl": -100.0},
        {"net_pnl": -200.0},
        {"net_pnl": -50.0},
    ]
    score = sharpe_per_trade(trades)
    assert score is not None
    assert score < 0, f"negative mean should give negative score, got {score}"


def main():
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
