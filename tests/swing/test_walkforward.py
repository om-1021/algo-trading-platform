"""Unit tests for src/swing/walkforward.py. Plain assert-based, runnable as
a script. Add new test_* functions and they auto-run from main().
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.swing.walkforward import generate_grid, sharpe_per_trade, rolling_folds


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


from datetime import date


def _make_trading_days(n: int, start: date = date(2023, 1, 2)):
    """Helper: return n consecutive weekdays starting from start."""
    days = []
    d = start
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d = d.fromordinal(d.toordinal() + 1)
    return days


def test_rolling_folds_basic_count():
    # 400 trading days, train=252, test=63, step=63 → fold 0 uses days[0:315];
    # next fold starts at index 63. Last valid fold has start such that
    # start + 315 ≤ 400. Number of folds: floor((400 - 315) / 63) + 1 = 1+1 = 2.
    days = _make_trading_days(400)
    folds = list(rolling_folds(days, train_days=252, test_days=63, step_days=63))
    assert len(folds) == 2, f"expected 2 folds, got {len(folds)}"


def test_rolling_folds_window_shapes():
    days = _make_trading_days(400)
    folds = list(rolling_folds(days, train_days=252, test_days=63, step_days=63))
    train_start, train_end, test_start, test_end = folds[0]
    # train_end and test_start should be adjacent in the trading-day index.
    assert train_start == days[0]
    assert train_end == days[251]
    assert test_start == days[252]
    assert test_end == days[314]


def test_rolling_folds_step_advances():
    days = _make_trading_days(400)
    folds = list(rolling_folds(days, train_days=252, test_days=63, step_days=63))
    # Fold 1 starts step_days (63) after fold 0.
    assert folds[1][0] == days[63]
    assert folds[1][2] == days[315]


def test_rolling_folds_too_short_history_yields_nothing():
    # 200 trading days < 252 train + 63 test → zero folds.
    days = _make_trading_days(200)
    folds = list(rolling_folds(days, train_days=252, test_days=63, step_days=63))
    assert folds == []


def test_rolling_folds_default_step_equals_test():
    # Spec: step=test_days for non-overlapping test windows.
    days = _make_trading_days(500)
    folds = list(rolling_folds(days, train_days=252, test_days=63, step_days=63))
    # All test windows should be non-overlapping.
    for i in range(len(folds) - 1):
        _, _, test_start_i, test_end_i = folds[i]
        _, _, test_start_j, _ = folds[i + 1]
        assert test_start_j > test_end_i, f"overlap between fold {i} and {i+1}"


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
