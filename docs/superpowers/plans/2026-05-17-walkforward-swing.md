# Walk-Forward Validation Harness (Swing Lane) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the swing-lane walk-forward harness — rolling 252/63/63 windows, ~30-combo grid for `EmaCrossover` (fast, slow), Sharpe-per-trade selection metric, universe-wide param selection, with a fixed-(20,50) baseline run on the same test window for every fold.

**Architecture:** Refactor `src/swing/backtest.py` to extract a private date-windowed core (`_backtest_window`) that both the existing full-history `run_backtest()` and the new walk-forward orchestrator can call. Add a new module `src/swing/walkforward.py` with pure helpers (`generate_grid`, `sharpe_per_trade`, `rolling_folds`) and the orchestrator (`run_walkforward`). Two new tables (`swing_walkforward_runs`, `swing_walkforward_folds`) added to `schema.sql`. Test-period trades reuse `swing_strategy_runs` / `swing_signals` / `swing_trades` under fresh `run_id`s; train-period trades are in-memory scaffolding only.

**Tech Stack:** Python 3.12, DuckDB (via existing `src/storage/db.py`), pandas, loguru. No new third-party dependencies. Tests are plain Python files with `assert`, runnable as `python tests/swing/test_walkforward.py`, matching the existing `scripts/smoke_test_swing.py` convention.

**Spec:** `docs/superpowers/specs/2026-05-17-walkforward-swing-design.md`

**Prereqs to verify before starting:**
- DuckDB at `data/algo.duckdb` populated with ≥ 1 year of daily bars for ≥ 1 symbol (run `python scripts/backfill_daily.py` if not)
- venv at `.venv/` with `requirements.txt` installed
- Working tree clean (`git status` empty)

---

## File Structure

| Path | Role | Action |
|---|---|---|
| `src/storage/schema.sql` | DDL source of truth | **Modify** — append two CREATE TABLE statements |
| `src/swing/backtest.py` | Strategy-run executor | **Modify** — extract `_backtest_window`, update `_load_bars`, keep `run_backtest` signature unchanged |
| `src/swing/walkforward.py` | WFO module | **Create** — `generate_grid`, `sharpe_per_trade`, `rolling_folds`, `run_walkforward` |
| `tests/swing/test_walkforward.py` | Unit tests for pure helpers | **Create** — assert-based, runnable as a script |
| `scripts/walkforward_swing.py` | Entry-point CLI | **Create** — invokes `run_walkforward` and prints per-fold + aggregate + per-symbol tables |
| `tests/swing/` directory | Test home | **Create** (new directory) |

---

## Task 1: Add the two walkforward tables to schema.sql

**Files:**
- Modify: `src/storage/schema.sql` (append at end, after `data_health_events`)

- [ ] **Step 1: Append the two new CREATE TABLE statements**

Open `src/storage/schema.sql` and append after the `data_health_events` block (after line 181):

```sql


-- ============================================================================
-- WALK-FORWARD VALIDATION (swing lane)
-- ============================================================================
-- One swing_walkforward_runs row per WFO invocation ("the study").
-- Two swing_walkforward_folds rows per fold: one for the optimized role
-- (best-on-train params) and one for the baseline role (fixed params).
-- Test-period trades live in the existing swing_trades table, linked via
-- swing_walkforward_folds.test_run_id → swing_strategy_runs.run_id.
-- Train-period trades are in-memory scaffolding and NOT persisted.

CREATE TABLE IF NOT EXISTS swing_walkforward_runs (
    wfo_id               VARCHAR PRIMARY KEY,    -- uuid
    strategy_name        VARCHAR NOT NULL,
    param_grid_json      VARCHAR NOT NULL,
    train_window_days    INTEGER NOT NULL,
    test_window_days     INTEGER NOT NULL,
    step_days            INTEGER NOT NULL,
    selection_metric     VARCHAR NOT NULL,
    baseline_params_json VARCHAR NOT NULL,
    started_at           TIMESTAMPTZ DEFAULT current_timestamp,
    status               VARCHAR NOT NULL        -- "running" | "complete" | "failed"
);

CREATE TABLE IF NOT EXISTS swing_walkforward_folds (
    fold_id                VARCHAR PRIMARY KEY,
    wfo_id                 VARCHAR NOT NULL,
    fold_index             INTEGER NOT NULL,
    train_start            DATE    NOT NULL,
    train_end              DATE    NOT NULL,
    test_start             DATE    NOT NULL,
    test_end               DATE    NOT NULL,
    role                   VARCHAR NOT NULL,     -- "optimized" | "baseline"
    chosen_params_json     VARCHAR NOT NULL,
    train_selection_score  DOUBLE,               -- NULL for role='baseline'
    test_run_id            VARCHAR NOT NULL,     -- → swing_strategy_runs.run_id
    test_summary_json      VARCHAR NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_wfo_folds_wfo
    ON swing_walkforward_folds(wfo_id);
```

- [ ] **Step 2: Apply the schema**

Run:

```powershell
& D:\algo-trading-platform-v2\.venv\Scripts\python.exe D:\algo-trading-platform-v2\scripts\init_db.py
```

Expected: `Schema initialized at D:\algo-trading-platform-v2\data\algo.duckdb` log line, exit 0.

- [ ] **Step 3: Verify the tables exist**

Run:

```powershell
& D:\algo-trading-platform-v2\.venv\Scripts\python.exe -c "import duckdb; con = duckdb.connect(r'D:\algo-trading-platform-v2\data\algo.duckdb', read_only=True); rows = con.sql(\"SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'swing_walkforward%' ORDER BY 1\").fetchall(); print(rows)"
```

Expected output:
```
[('swing_walkforward_folds',), ('swing_walkforward_runs',)]
```

- [ ] **Step 4: Commit**

```powershell
git -C "D:\algo-trading-platform-v2" add src/storage/schema.sql
git -C "D:\algo-trading-platform-v2" commit -m "feat(schema): add walk-forward tables (swing lane)`n`nTwo new tables: swing_walkforward_runs (one row per study) and`nswing_walkforward_folds (two rows per fold; optimized + baseline roles).`nTest-period trades reuse existing swing_trades via test_run_id.`n`nCo-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Refactor `backtest.py` — extract `_backtest_window`

**Files:**
- Modify: `src/swing/backtest.py`

**Why this refactor:** Walk-forward needs to (a) run the strategy on a date-bounded slice of bars, and (b) sometimes compute trades without persisting them (grid scoring on the train window). The cleanest path is to extract a private `_backtest_window` core that takes optional date bounds and a `persist` flag. The public `run_backtest()` becomes a thin wrapper — its signature is unchanged so existing callers (`scripts/backtest_swing.py`, `scripts/smoke_test_swing.py`) keep working.

- [ ] **Step 1: Open `src/swing/backtest.py` and read the current file end-to-end**

Confirm you see: `DEFAULT_COST_BPS_PER_LEG`, `_load_bars`, `_create_run`, `_persist_signals`, `_pair_signals_into_trades`, `_persist_trades`, `_summary`, `run_backtest`.

- [ ] **Step 2: Update `_load_bars` to accept optional date bounds**

Replace the existing `_load_bars` function with:

```python
def _load_bars(
    instrument_key: str,
    from_date: date | None = None,
    to_date: date | None = None,
) -> pd.DataFrame:
    """Load daily bars for an instrument, optionally bounded by date.

    Bounds are inclusive on both ends. None means no bound on that side.
    """
    clauses = ["instrument_key = ?"]
    params: list = [instrument_key]
    if from_date is not None:
        clauses.append("bar_date >= ?")
        params.append(from_date)
    if to_date is not None:
        clauses.append("bar_date <= ?")
        params.append(to_date)
    where = " AND ".join(clauses)
    with get_conn() as conn:
        df = conn.execute(
            f"""
            SELECT bar_date, open, high, low, close, volume
            FROM market_bars_daily
            WHERE {where}
            ORDER BY bar_date
            """,
            params,
        ).fetchdf()
    if df.empty:
        return df
    df["bar_date"] = pd.to_datetime(df["bar_date"])
    return df.set_index("bar_date")
```

You'll also need to add `from datetime import date` to the imports at the top if it's not already imported (it should be — verify line 24).

- [ ] **Step 3: Replace `run_backtest` with the extracted core + thin wrapper**

Find the existing `run_backtest` function near the bottom of the file. Replace it (and only it — keep the helpers above unchanged) with:

```python
def _backtest_window(
    strategy: SwingStrategy,
    instrument_keys: list[str],
    from_date: date | None = None,
    to_date: date | None = None,
    cost_bps_per_leg: float = DEFAULT_COST_BPS_PER_LEG,
    capital_per_trade: float = DEFAULT_CAPITAL_PER_TRADE,
    persist: bool = True,
) -> dict[str, Any]:
    """Run strategy on a date-bounded window across the given universe.

    When persist=True: creates a fresh swing_strategy_runs row, writes
    swing_signals and swing_trades, returns summary including run_id.

    When persist=False: computes trades in memory only, returns summary
    including the trade list. Used by walk-forward grid scoring so train-
    window trades don't pollute the persisted strategy-run history.
    """
    run_id = _create_run(strategy) if persist else None

    all_signals: list[SwingSignal] = []
    for key in instrument_keys:
        bars = _load_bars(key, from_date=from_date, to_date=to_date)
        if bars.empty:
            logger.warning("No bars for {} in window {}..{}", key, from_date, to_date)
            continue
        sigs = strategy.generate_signals(bars, key)
        if sigs:
            logger.debug("  {} → {} signals", key, len(sigs))
        all_signals.extend(sigs)

    if persist:
        sig_id_map = _persist_signals(run_id, all_signals)
    else:
        # Fabricate signal ids in-memory so _pair_signals_into_trades has its mapping.
        sig_id_map = {
            (s.instrument_key, s.signal_ts): str(uuid.uuid4()) for s in all_signals
        }

    trades = _pair_signals_into_trades(
        run_id or "", all_signals, sig_id_map, cost_bps_per_leg, capital_per_trade,
    )

    if persist:
        _persist_trades(trades)

    summary = _summary(trades, run_id or "")
    summary["trades_list"] = trades  # always include for caller use (WFO scoring)
    if persist:
        logger.success("Backtest complete: {}", {k: v for k, v in summary.items() if k != "trades_list"})
    return summary


def run_backtest(
    strategy: SwingStrategy,
    instrument_keys: list[str],
    cost_bps_per_leg: float = DEFAULT_COST_BPS_PER_LEG,
    capital_per_trade: float = DEFAULT_CAPITAL_PER_TRADE,
) -> dict[str, Any]:
    """Run strategy over full history of the given universe.

    Backwards-compatible wrapper around _backtest_window. Existing callers
    keep working without changes. The returned dict does NOT include the
    in-memory trades_list — that's an internal detail.
    """
    summary = _backtest_window(
        strategy, instrument_keys,
        from_date=None, to_date=None,
        cost_bps_per_leg=cost_bps_per_leg,
        capital_per_trade=capital_per_trade,
        persist=True,
    )
    summary.pop("trades_list", None)
    return summary
```

Also: the existing `_pair_signals_into_trades` references `sig_id_map[(s.instrument_key, s.signal_ts)]` — that still works. Verify the existing helper functions (`_create_run`, `_persist_signals`, `_pair_signals_into_trades`, `_persist_trades`, `_summary`) are unchanged.

- [ ] **Step 4: Run the smoke test to verify backwards compatibility**

Run:

```powershell
& D:\algo-trading-platform-v2\.venv\Scripts\python.exe D:\algo-trading-platform-v2\scripts\smoke_test_swing.py
```

Expected: ends with `✓ All assertions passed`, exit 0. Per-symbol P&L should still show TRENDUP positive-ish, SIDEWAYS bleeding, TRENDDOWN small loss (consistent with prior runs).

- [ ] **Step 5: Run the real-data backtest and confirm output matches**

Run:

```powershell
$env:PYTHONIOENCODING="utf-8"; & D:\algo-trading-platform-v2\.venv\Scripts\python.exe D:\algo-trading-platform-v2\scripts\backtest_swing.py 2>&1 | Select-Object -Last 5
```

Expected: the `Backtest complete: {...}` line should show `'trades': 299, 'wins': 111, 'losses': 188, 'win_rate': 0.3712, 'total_net_pnl': 115773.64` — same numbers as the previous run on the same data. Any deviation here means the refactor changed behavior; investigate before continuing.

- [ ] **Step 6: Commit**

```powershell
git -C "D:\algo-trading-platform-v2" add src/swing/backtest.py
git -C "D:\algo-trading-platform-v2" commit -m "refactor(swing): extract _backtest_window core for WFO reuse`n`nrun_backtest() is now a thin wrapper around the new private`n_backtest_window(), which accepts optional date bounds and a persist`nflag. With persist=False, trades are computed in-memory only and returned`nvia the summary's trades_list field — used by walk-forward grid scoring`nso train-window trades never land in swing_trades.`n`nSignature of run_backtest() is unchanged; smoke test and real-data`nbacktest produce identical results.`n`nCo-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Create `walkforward.py` skeleton + `generate_grid` (TDD)

**Files:**
- Create: `tests/swing/test_walkforward.py`
- Create: `src/swing/walkforward.py`

- [ ] **Step 1: Create the test directory and write a failing test for `generate_grid`**

Create `tests/swing/test_walkforward.py` with this content:

```python
"""Unit tests for src/swing/walkforward.py. Plain assert-based, runnable as
a script. Add new test_* functions and they auto-run from main().
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.swing.walkforward import generate_grid


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
    # Spec says "~30 valid pairs". Tolerate 25..40 in case we tweak grid edges.
    assert 25 <= len(grid) <= 40, f"unexpected grid size {len(grid)}"


def main():
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  ✗ {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the test to confirm it fails (module doesn't exist yet)**

Run:

```powershell
& D:\algo-trading-platform-v2\.venv\Scripts\python.exe D:\algo-trading-platform-v2\tests\swing\test_walkforward.py
```

Expected: `ModuleNotFoundError: No module named 'src.swing.walkforward'` (or similar). Exit 1.

- [ ] **Step 3: Create `src/swing/walkforward.py` with `generate_grid`**

Create the file with this content:

```python
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
```

- [ ] **Step 4: Re-run the test to confirm it passes**

```powershell
& D:\algo-trading-platform-v2\.venv\Scripts\python.exe D:\algo-trading-platform-v2\tests\swing\test_walkforward.py
```

Expected:
```
  ✓ test_generate_grid_returns_only_valid_pairs
  ✓ test_generate_grid_uses_documented_values
  ✓ test_generate_grid_excludes_invalid_pairs
  ✓ test_generate_grid_size_in_range
4/4 passed
```

(Exact pair count: 7×6 = 42 raw, of which `(5,30) (5,40) ... (25,200)` filtered to `fast<slow` = need to count. `f=5` → 6 valid; `f=8` → 6; `f=10` → 6; `f=13` → 6; `f=15` → 6; `f=20` → 5 (drops 30); `f=25` → 4 (drops 30, 40). Total = 39. That's within 25..40.)

- [ ] **Step 5: Commit**

```powershell
git -C "D:\algo-trading-platform-v2" add tests/swing/test_walkforward.py src/swing/walkforward.py
git -C "D:\algo-trading-platform-v2" commit -m "feat(swing): walkforward.generate_grid + tests`n`n39 valid (fast, slow) EMA pairs: fast in {5,8,10,13,15,20,25} times`nslow in {30,40,50,60,100,200} with fast < slow. Matches spec §2 'coarse'`ngrid choice.`n`nTests are plain assert-based, runnable as 'python tests/swing/test_walkforward.py'`nin keeping with existing scripts/smoke_test_swing.py convention.`n`nCo-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Add `sharpe_per_trade` (TDD)

**Files:**
- Modify: `tests/swing/test_walkforward.py`
- Modify: `src/swing/walkforward.py`

- [ ] **Step 1: Append failing tests for `sharpe_per_trade`**

Open `tests/swing/test_walkforward.py` and add this AFTER the existing `from src.swing.walkforward import generate_grid` line (replace that line):

```python
from src.swing.walkforward import generate_grid, sharpe_per_trade
```

Then append these test functions BEFORE the `def main():` line:

```python
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
```

- [ ] **Step 2: Run the tests; the new four should fail with ImportError**

```powershell
& D:\algo-trading-platform-v2\.venv\Scripts\python.exe D:\algo-trading-platform-v2\tests\swing\test_walkforward.py
```

Expected: `ImportError: cannot import name 'sharpe_per_trade' from 'src.swing.walkforward'`. Exit 1.

- [ ] **Step 3: Implement `sharpe_per_trade` in `walkforward.py`**

Append to `src/swing/walkforward.py`:

```python
import statistics


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
```

- [ ] **Step 4: Re-run tests; all 9 pass**

```powershell
& D:\algo-trading-platform-v2\.venv\Scripts\python.exe D:\algo-trading-platform-v2\tests\swing\test_walkforward.py
```

Expected:
```
  ✓ test_generate_grid_returns_only_valid_pairs
  ✓ test_generate_grid_uses_documented_values
  ✓ test_generate_grid_excludes_invalid_pairs
  ✓ test_generate_grid_size_in_range
  ✓ test_sharpe_per_trade_basic
  ✓ test_sharpe_per_trade_zero_trades_returns_none
  ✓ test_sharpe_per_trade_one_trade_returns_none
  ✓ test_sharpe_per_trade_zero_stdev_returns_none
  ✓ test_sharpe_per_trade_negative_mean
9/9 passed
```

- [ ] **Step 5: Commit**

```powershell
git -C "D:\algo-trading-platform-v2" add tests/swing/test_walkforward.py src/swing/walkforward.py
git -C "D:\algo-trading-platform-v2" commit -m "feat(swing): sharpe_per_trade selection metric + tests`n`nmean(net_pnl) / stdev(net_pnl) across a flat list of trades, with explicit`nNone returns for the three undefined cases (empty, n=1, zero stdev). Used`nby walk-forward to score (fast, slow) pairs on each train window.`n`nCo-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Add `rolling_folds` (TDD)

**Files:**
- Modify: `tests/swing/test_walkforward.py`
- Modify: `src/swing/walkforward.py`

**Notes on window semantics:** `rolling_folds` works in **trading days**, not calendar days. The caller passes the sorted unique list of trading dates that exist in `market_bars_daily` (across the WFO universe), and we slice it by index. This avoids weekend/holiday off-by-ones that calendar arithmetic would introduce.

- [ ] **Step 1: Append failing tests**

Update the import line in `tests/swing/test_walkforward.py`:

```python
from src.swing.walkforward import generate_grid, sharpe_per_trade, rolling_folds
```

Append before `def main():`:

```python
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
    # 400 trading days, train=252, test=63, step=63 → fold 0 starts at index 0,
    # uses 252 train + 63 test = 315 days, ends at index 314. Next fold starts
    # at index 63. Last valid fold has start such that start+315 ≤ 400.
    # Number of folds: floor((400 - 315) / 63) + 1 = floor(85/63)+1 = 1+1 = 2.
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
    # Spec says step=test_days by default so test windows tile non-overlapping.
    days = _make_trading_days(500)
    folds = list(rolling_folds(days, train_days=252, test_days=63, step_days=63))
    # All test windows should be non-overlapping.
    for i in range(len(folds) - 1):
        _, _, test_start_i, test_end_i = folds[i]
        _, _, test_start_j, _ = folds[i + 1]
        assert test_start_j > test_end_i, f"overlap between fold {i} and {i+1}"
```

- [ ] **Step 2: Run; expect ImportError**

```powershell
& D:\algo-trading-platform-v2\.venv\Scripts\python.exe D:\algo-trading-platform-v2\tests\swing\test_walkforward.py
```

Expected: `ImportError: cannot import name 'rolling_folds'`.

- [ ] **Step 3: Implement `rolling_folds` in `walkforward.py`**

Append to `src/swing/walkforward.py` (add the `date` import to the top of the file first if missing):

```python
from datetime import date
from typing import Iterator


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
```

- [ ] **Step 4: Re-run tests; all 14 pass**

```powershell
& D:\algo-trading-platform-v2\.venv\Scripts\python.exe D:\algo-trading-platform-v2\tests\swing\test_walkforward.py
```

Expected: `14/14 passed`.

- [ ] **Step 5: Commit**

```powershell
git -C "D:\algo-trading-platform-v2" add tests/swing/test_walkforward.py src/swing/walkforward.py
git -C "D:\algo-trading-platform-v2" commit -m "feat(swing): rolling_folds generator + tests`n`nSlides (train_days + test_days) window over the trading-day index.`nWorks in trading-day units, not calendar days — caller supplies the`nsorted unique list of dates that exist in market_bars_daily.`nNon-overlapping test windows when step_days == test_days (the WFO default).`n`nCo-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Implement `run_walkforward` orchestrator

**Files:**
- Modify: `src/swing/walkforward.py`

This task assembles the orchestrator. It's larger than the previous tasks (~120 lines) but stays in one file and has one clear job: tie helpers + `_backtest_window` into the end-to-end WFO loop. No tests at the function level — we verify with the end-to-end script in Task 8.

- [ ] **Step 1: Append the orchestrator + imports**

Replace the imports section at the top of `src/swing/walkforward.py` with:

```python
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
```

Then append (after the existing `rolling_folds` definition) the orchestrator:

```python
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
    return wfo_id
```

- [ ] **Step 2: Verify the test file still passes (we didn't break helpers)**

```powershell
& D:\algo-trading-platform-v2\.venv\Scripts\python.exe D:\algo-trading-platform-v2\tests\swing\test_walkforward.py
```

Expected: `14/14 passed`.

- [ ] **Step 3: Verify the orchestrator imports cleanly (no NameErrors etc.)**

Run:

```powershell
& D:\algo-trading-platform-v2\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0, r'D:\algo-trading-platform-v2'); from src.swing.walkforward import run_walkforward; print('ok')"
```

Expected output: `ok`. Any ImportError or NameError here means something in the orchestrator referenced an undefined symbol — fix before continuing. (The `sys.path.insert` makes the check work no matter which directory PowerShell is currently in.)

- [ ] **Step 4: Commit**

```powershell
git -C "D:\algo-trading-platform-v2" add src/swing/walkforward.py
git -C "D:\algo-trading-platform-v2" commit -m "feat(swing): run_walkforward orchestrator`n`nFor each fold: grid-search EmaCrossover (fast, slow) on train window`n(in-memory only), score by sharpe_per_trade, pick the winner (tie-break:`nsmallest fast+slow), then run the winner AND fixed (20,50) baseline on the`ntest window with persistence on. Two swing_walkforward_folds rows per fold`n(optimized + baseline). Train-window trades are not persisted.`n`nIf the entire grid is disqualified on a train window, the fold is skipped`nand a warn-level data_health_events row is written.`n`nCo-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Create `scripts/walkforward_swing.py` entry point

**Files:**
- Create: `scripts/walkforward_swing.py`

- [ ] **Step 1: Create the entry-point script**

Create `scripts/walkforward_swing.py` with this content:

```python
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
```

- [ ] **Step 2: Smoke-check the script loads without syntax/import errors**

`scripts/` isn't a package, so import it directly via importlib:

```powershell
& D:\algo-trading-platform-v2\.venv\Scripts\python.exe -c "import importlib.util; spec = importlib.util.spec_from_file_location('w', r'D:\algo-trading-platform-v2\scripts\walkforward_swing.py'); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); print('ok')"
```

Expected: `ok`. We don't run `main()` here — that's Task 8.

- [ ] **Step 3: Commit (script only — full e2e run is Task 8)**

```powershell
git -C "D:\algo-trading-platform-v2" add scripts/walkforward_swing.py
git -C "D:\algo-trading-platform-v2" commit -m "feat(swing): walkforward_swing.py entry-point script`n`nCalls run_walkforward over the in-DB universe and prints per-fold,`naggregate, and per-symbol tables. UTF-8 stdout reconfigure for the ₹`ncharacter on Windows.`n`nCo-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: End-to-end run + spec §1.5 sanity-check queries

This is where we prove the harness actually does what the spec claims.

**Files:**
- No file changes. This task runs the script and runs the three sanity-check queries from spec §1.5.

- [ ] **Step 1: Run the end-to-end harness**

```powershell
$env:PYTHONIOENCODING="utf-8"; & D:\algo-trading-platform-v2\.venv\Scripts\python.exe D:\algo-trading-platform-v2\scripts\walkforward_swing.py 2>&1 | Tee-Object -FilePath D:\algo-trading-platform-v2\data\wfo_run.log | Select-Object -Last 80
```

Expected: The script logs each fold, then prints three tables (per-fold, aggregate, per-symbol). Save the printed `wfo_id` — you'll need it for the next step. Look for:
- Exit 0
- ~7 folds completed
- Aggregate shows both `optimized` and `baseline` rows
- Per-symbol breakdown has rows in P&L-descending order

If a fold reports "no valid grid combo; skipping," check `data_health_events` for the warning. If MANY folds skip, something's wrong — investigate.

- [ ] **Step 2: Capture the wfo_id**

Read the printed `wfo_id` from the previous output. (Alternative: query it from the DB.)

```powershell
& D:\algo-trading-platform-v2\.venv\Scripts\python.exe -c "import duckdb; con = duckdb.connect(r'D:\algo-trading-platform-v2\data\algo.duckdb', read_only=True); print(con.sql(\"SELECT wfo_id, status FROM swing_walkforward_runs ORDER BY started_at DESC LIMIT 1\").fetchone())"
```

Expected: a tuple like `('abc123-...', 'complete')`. Store the wfo_id for the next steps.

- [ ] **Step 3: Run spec §1.5 sanity-check query #1 (all-trades-of-strategy-on-symbol)**

This query proves: every WFO test trade is reachable via the strategy-centric chain.

```powershell
$env:PYTHONIOENCODING="utf-8"; & D:\algo-trading-platform-v2\.venv\Scripts\python.exe -c "import duckdb; con = duckdb.connect(r'D:\algo-trading-platform-v2\data\algo.duckdb', read_only=True); df = con.sql(\"\"\"SELECT t.trade_id, t.entry_ts, t.exit_ts, ROUND(t.net_pnl, 2) AS net_pnl FROM swing_trades t JOIN swing_strategy_runs r USING (run_id) JOIN instruments i USING (instrument_key) JOIN swing_walkforward_folds f ON f.test_run_id = t.run_id WHERE r.strategy_name = 'ema_crossover' AND i.tradingsymbol = 'RELIANCE' AND f.role = 'optimized' ORDER BY t.entry_ts\"\"\").fetchdf(); print(df.to_string(index=False)); print(f'\\n{len(df)} trades')"
```

Expected: a small table with RELIANCE trades from optimized test windows (probably 1-3 rows depending on how many test windows had crosses). Even zero rows is OK — what matters is the query runs without error.

- [ ] **Step 4: Run spec §1.5 sanity-check query #2 (per-symbol P&L for WFO)**

This automatically picks up the latest WFO run; no manual wfo_id substitution needed.

```powershell
$env:PYTHONIOENCODING="utf-8"; & D:\algo-trading-platform-v2\.venv\Scripts\python.exe -c "import duckdb; con = duckdb.connect(r'D:\algo-trading-platform-v2\data\algo.duckdb', read_only=True); latest = con.sql(\"SELECT wfo_id FROM swing_walkforward_runs ORDER BY started_at DESC LIMIT 1\").fetchone()[0]; df = con.sql(\"\"\"SELECT i.tradingsymbol, ROUND(SUM(t.net_pnl), 2) AS total_net, COUNT(*) AS n_trades FROM swing_trades t JOIN swing_strategy_runs r USING (run_id) JOIN swing_walkforward_folds f ON f.test_run_id = t.run_id JOIN instruments i USING (instrument_key) WHERE f.wfo_id = ? AND f.role = 'optimized' GROUP BY 1 ORDER BY 2 DESC NULLS LAST LIMIT 10\"\"\", [latest]).fetchdf(); print(df.to_string(index=False))"
```

Expected: top-10 symbols by net P&L. Compare against the per-symbol breakdown the script printed in Step 1; the top entries should match (same wfo_id, same role).

- [ ] **Step 5: Run spec §1.5 sanity-check query #3 (strategy comparison)**

Even with only one strategy in the system, this query should run cleanly and return a single row for `ema_crossover` — proving the strategy-grouped path works for future multi-strategy comparison.

```powershell
$env:PYTHONIOENCODING="utf-8"; & D:\algo-trading-platform-v2\.venv\Scripts\python.exe -c "import duckdb; con = duckdb.connect(r'D:\algo-trading-platform-v2\data\algo.duckdb', read_only=True); df = con.sql(\"\"\"SELECT r.strategy_name, COUNT(*) AS trades, ROUND(SUM(t.net_pnl), 2) AS total_net FROM swing_trades t JOIN swing_strategy_runs r USING (run_id) JOIN swing_walkforward_folds f ON f.test_run_id = t.run_id GROUP BY 1\"\"\").fetchdf(); print(df.to_string(index=False))"
```

Expected: one row with `strategy_name = 'ema_crossover'`, the total trade count across WFO test windows, and the aggregated net P&L. When more strategies are added later, this query will gain rows automatically.

- [ ] **Step 6: Verify counts add up**

Sanity check that the fold-rows and the test_run_ids are consistent.

```powershell
& D:\algo-trading-platform-v2\.venv\Scripts\python.exe -c "import duckdb; con = duckdb.connect(r'D:\algo-trading-platform-v2\data\algo.duckdb', read_only=True); n_folds = con.sql(\"SELECT COUNT(*) FROM swing_walkforward_folds\").fetchone()[0]; n_runs_via_folds = con.sql(\"SELECT COUNT(DISTINCT test_run_id) FROM swing_walkforward_folds\").fetchone()[0]; n_test_runs = con.sql(\"SELECT COUNT(*) FROM swing_strategy_runs r WHERE EXISTS (SELECT 1 FROM swing_walkforward_folds f WHERE f.test_run_id = r.run_id)\").fetchone()[0]; print(f'fold rows: {n_folds}'); print(f'distinct test_run_ids in folds: {n_runs_via_folds}'); print(f'matching swing_strategy_runs rows: {n_test_runs}'); assert n_runs_via_folds == n_test_runs, 'mismatch'; print('OK')"
```

Expected: `fold rows == 2 × #folds_executed`, `distinct test_run_ids == fold rows` (each fold gets its own run_id per role), `matching swing_strategy_runs rows == distinct test_run_ids`. Final line: `OK`.

- [ ] **Step 7: Sanity check: train trades did NOT leak into swing_trades**

The grid-scoring step uses `persist=False`. Verify no scoring-only trades landed in `swing_trades`.

Train-only trades would have a `run_id` that exists in NO `swing_strategy_runs` row — but our schema design rules that out (run_id NOT NULL in swing_trades + every persist-true call inserts the run row first). The right test: every run_id in swing_trades is reachable from swing_strategy_runs.

```powershell
& D:\algo-trading-platform-v2\.venv\Scripts\python.exe -c "import duckdb; con = duckdb.connect(r'D:\algo-trading-platform-v2\data\algo.duckdb', read_only=True); orphans = con.sql(\"SELECT COUNT(*) FROM swing_trades t WHERE NOT EXISTS (SELECT 1 FROM swing_strategy_runs r WHERE r.run_id = t.run_id)\").fetchone()[0]; assert orphans == 0, f'{orphans} orphan trades — train trades leaked'; print(f'orphan trades: {orphans} ✓')"
```

Expected: `orphan trades: 0 ✓`.

- [ ] **Step 8: Inspect data_health_events for any walk-forward warnings**

```powershell
& D:\algo-trading-platform-v2\.venv\Scripts\python.exe -c "import duckdb; con = duckdb.connect(r'D:\algo-trading-platform-v2\data\algo.duckdb', read_only=True); df = con.sql(\"SELECT event_ts, severity, message FROM data_health_events WHERE component = 'walkforward' ORDER BY event_ts DESC LIMIT 20\").fetchdf(); print(df.to_string(index=False) if len(df) else '(no walkforward events)')"
```

Expected: `(no walkforward events)` is ideal — means every fold scored at least one grid combo. If folds were skipped, you'll see warn entries here.

- [ ] **Step 9: Commit + push everything**

```powershell
git -C "D:\algo-trading-platform-v2" log --oneline -8
git -C "D:\algo-trading-platform-v2" status --short
git -C "D:\algo-trading-platform-v2" push origin main
```

Expected: ~7 new commits since the prior `main`. `git status` empty. Push succeeds.

---

## Acceptance criteria (summary)

The walk-forward harness is considered complete when:

1. ✅ Schema: `swing_walkforward_runs` and `swing_walkforward_folds` exist in DuckDB (Task 1 step 3)
2. ✅ Refactor: `python scripts/smoke_test_swing.py` and `python scripts/backtest_swing.py` produce results identical to the pre-refactor baseline (Task 2 steps 4-5)
3. ✅ Unit tests: `python tests/swing/test_walkforward.py` prints `14/14 passed` (Task 5 step 4)
4. ✅ End-to-end: `python scripts/walkforward_swing.py` completes with exit 0 and prints all three tables (Task 8 step 1)
5. ✅ Spec §1.5 query #1 (all-trades-of-strategy-on-symbol) runs without error (Task 8 step 3)
6. ✅ Spec §1.5 query #2 (per-symbol P&L for WFO) matches the printed per-symbol breakdown (Task 8 step 4)
7. ✅ Spec §1.5 query #3 (cross-strategy comparison) returns a row for `ema_crossover` (Task 8 step 5)
8. ✅ Fold/run consistency check passes (Task 8 step 6)
9. ✅ Zero orphan trades — train trades did not leak (Task 8 step 7)
10. ✅ Commits pushed to `origin/main` (Task 8 step 9)

---

## Out of scope (per spec §6, do NOT do here)

- Per-symbol param selection (universe-wide only)
- Multiple strategies (EmaCrossover only; the harness is generic, other strategies come later)
- Streamlit visualization (roadmap item 3, separate plan)
- Intraday walk-forward (intraday lane is separate work)
- Anchored windows (rolling only)
- Annualized Sharpe with risk-free rate (per-trade Sharpe-like is sufficient)
- Statistical significance tests on optimized-vs-baseline
- Parallel grid evaluation
