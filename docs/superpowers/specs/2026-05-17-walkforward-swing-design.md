# Swing Walk-Forward Validation Harness — Design

**Date:** 2026-05-17
**Status:** approved by user; ready for implementation plan
**Lane:** swing only (intraday harness is separate work)
**Roadmap reference:** `docs/roadmap.md` item 2 — "most important next addition"

---

## 1. Why this exists

Single-shot backtests with one parameter pair over full history are overfit by
construction. The architecture doc's promotion pipeline calls Stage 3
"walk-forward — rolling train/test, must show out-of-sample edge." This harness
implements Stage 3 for the swing lane.

The harness must surface, in plain numbers, **whether picking the
best-on-train (fast, slow) generalizes to the next unseen window**. If it
doesn't beat a fixed baseline out-of-sample, the lesson is that optimization
is noise — the strategy itself is the story.

---

## 1.5 Strategy-centric invariants the harness must preserve

The platform's central principle is that **every trade is classifiable by the
strategy that produced it**, so any strategy (popular or homegrown,
universe-wide or single-stock) can be backtested, compared against others,
and analyzed for per-symbol fit. The walk-forward harness must not weaken
that.

These invariants are enforced and must continue to hold:

1. **Every persisted trade has a `run_id`.** Trades without a strategy run
   row are illegal — `swing_trades.run_id` is `NOT NULL`.
2. **Every `run_id` resolves to `(strategy_name, strategy_version,
   params_json)`** via `swing_strategy_runs`. No mystery trades.
3. **A strategy's universe is the `instrument_keys` list passed to its
   backtest call.** A strategy can run on all 51 symbols or on a single
   symbol — both produce one `swing_strategy_runs` row. Per-stock strategies
   are not a future feature; they're a supported usage pattern today.
4. **Train-period trades from grid search are scaffolding, never persisted.**
   Persisting them would let someone accidentally aggregate scoring trades
   into "strategy performance," which is the kind of data hygiene failure
   walk-forward exists to prevent.
5. **Walk-forward folds add context, not new trade paths.**
   `swing_walkforward_folds` exists to record *which window, which params,
   which role* — every trade is still reachable via the existing
   `swing_trades → swing_strategy_runs → strategy_name` chain.

Queries the harness must keep enabling (sanity check during implementation):

```sql
-- "Show me every out-of-sample trade ever taken under ema_crossover
--  on RELIANCE across all WFO studies."
SELECT t.* FROM swing_trades t
JOIN swing_strategy_runs r USING (run_id)
JOIN instruments i USING (instrument_key)
JOIN swing_walkforward_folds f ON f.test_run_id = t.run_id
WHERE r.strategy_name = 'ema_crossover'
  AND i.tradingsymbol  = 'RELIANCE'
  AND f.role            = 'optimized';

-- "Per-symbol net P&L under the optimized walk-forward of this strategy."
SELECT i.tradingsymbol,
       ROUND(SUM(t.net_pnl), 2) AS total_net,
       COUNT(*)                  AS n_trades
FROM swing_trades t
JOIN swing_strategy_runs r USING (run_id)
JOIN swing_walkforward_folds f ON f.test_run_id = t.run_id
JOIN instruments i USING (instrument_key)
WHERE f.wfo_id = '<wfo_uuid>' AND f.role = 'optimized'
GROUP BY 1 ORDER BY 2 DESC;

-- "Compare two strategies head-to-head on out-of-sample trades only."
SELECT r.strategy_name,
       COUNT(*) AS trades, ROUND(SUM(t.net_pnl), 2) AS total_net
FROM swing_trades t
JOIN swing_strategy_runs r USING (run_id)
JOIN swing_walkforward_folds f ON f.test_run_id = t.run_id
WHERE r.strategy_name IN ('ema_crossover', 'rsi_meanrev')
GROUP BY 1;
```

---

## 2. What it does (the loop)

Slides a `(train_window_days=252, test_window_days=63, step_days=63)` triple
across the daily-bar history for all instruments present in
`market_bars_daily`. For each fold:

1. **Train.** For every (fast, slow) pair in the coarse grid, run the
   `EmaCrossover` strategy on the train window across all instruments. Flatten
   the resulting trades into a single list (concatenation across symbols, not
   per-symbol-then-averaged) and score the pair by `mean(net_pnl) /
   stdev(net_pnl)` over that flat list. Pair with the highest score wins.
   Ties broken by smaller (fast + slow) (Occam-ish).
2. **Test (optimized role).** Re-run the winning pair on the test window
   across all instruments. Persist signals and trades to
   `swing_signals` / `swing_trades` under a fresh `run_id`. These are
   out-of-sample trades.
3. **Test (baseline role).** Re-run **fixed (20, 50)** on the test window
   across all instruments. Persist under another fresh `run_id`. Lets us
   compare "optimized per fold" vs "always 20/50."

Folds advance by `step_days`. Train data slides forward (rolling, not
anchored), so the optimizer cannot peek at very old / out-of-regime data.

### Grid

Coarse grid: `fast ∈ {5, 8, 10, 13, 15, 20, 25}`,
`slow ∈ {30, 40, 50, 60, 100, 200}`, filtered to `fast < slow`. About 30
valid pairs.

### Window sizing

- 252 trading days ≈ 1 year (standard yardstick)
- 63 trading days ≈ 1 quarter
- step = test_window so test windows tile, no overlap

With ~743 bars of history, this yields ~7 folds.

### Selection metric

`sharpe_per_trade = mean(net_pnl) / stdev(net_pnl)` over all train-window
trades for that (fast, slow) pair across the universe. Per-trade unit (not
per-bar) because trade count varies wildly across parameter pairs and we want
risk-adjusted comparison.

Edge cases:
- Zero trades on train window → score is `None`, pair is disqualified for
  that fold.
- One trade on train window → stdev undefined → score is `None`, disqualified.
- All train trades survive → final selection set is `[(params, score), ...]`
  with at least one entry; max picks the winner. If the entire grid is
  disqualified (very short train window, very strict params), the fold logs a
  `data_health_events` row with severity=`warn` and is skipped (no optimized
  or baseline run persisted for that fold).

### Compute envelope

7 folds × 30 grid combos × 51 symbols × ~750 train bars per symbol ≈ 8M
EWM cell-evaluations through pandas. Empirically expected runtime: under one
minute on the user's laptop. No parallelization needed in v1.

---

## 3. Data shape

Three additions, no changes to existing tables. Lane prefix `swing_`
preserved per `CLAUDE.md` §6.

### New table: `swing_walkforward_runs`

```sql
CREATE TABLE IF NOT EXISTS swing_walkforward_runs (
    wfo_id              VARCHAR PRIMARY KEY,    -- uuid
    strategy_name       VARCHAR NOT NULL,       -- "ema_crossover"
    param_grid_json     VARCHAR NOT NULL,       -- the grid we searched
    train_window_days   INTEGER NOT NULL,
    test_window_days    INTEGER NOT NULL,
    step_days           INTEGER NOT NULL,
    selection_metric    VARCHAR NOT NULL,       -- "sharpe_per_trade"
    baseline_params_json VARCHAR NOT NULL,      -- e.g. {"fast":20,"slow":50}
    started_at          TIMESTAMPTZ DEFAULT now(),
    status              VARCHAR NOT NULL        -- "running" | "complete" | "failed"
);
```

One row per WFO invocation (the "study").

### New table: `swing_walkforward_folds`

```sql
CREATE TABLE IF NOT EXISTS swing_walkforward_folds (
    fold_id                 VARCHAR PRIMARY KEY,    -- uuid
    wfo_id                  VARCHAR NOT NULL,       -- → swing_walkforward_runs
    fold_index              INTEGER NOT NULL,
    train_start             DATE    NOT NULL,
    train_end               DATE    NOT NULL,
    test_start              DATE    NOT NULL,
    test_end                DATE    NOT NULL,
    role                    VARCHAR NOT NULL,       -- "optimized" | "baseline"
    chosen_params_json      VARCHAR NOT NULL,       -- winner-of-train, or baseline
    train_selection_score   DOUBLE,                 -- only for role='optimized'; NULL for 'baseline'
    test_run_id             VARCHAR NOT NULL,       -- → swing_strategy_runs.run_id
    test_summary_json       VARCHAR NOT NULL        -- {trades, wins, losses, win_rate,
                                                    --  total_net_pnl, avg_trade_pnl,
                                                    --  best_trade, worst_trade,
                                                    --  sharpe_per_trade}
                                                    -- same shape as run_backtest() summary
                                                    -- plus sharpe_per_trade field
);

CREATE INDEX IF NOT EXISTS idx_wfo_folds_wfo
    ON swing_walkforward_folds(wfo_id);
```

Two rows per fold (one `optimized`, one `baseline`).

### How test trades attach

Test-period strategy runs go into existing `swing_strategy_runs` /
`swing_signals` / `swing_trades` under a fresh `run_id` per fold per role.
The fold row's `test_run_id` is the bridge.

This means `swing_strategy_runs` accumulates `2 × num_folds` rows per WFO
study (e.g., 14 rows for 7 folds). That's fine — it preserves the existing
"every set of strategy trades has a run_id and a row in swing_strategy_runs"
invariant.

### What does NOT get persisted

Train-window trades are computed in-memory only during grid search. We do
**not** write them to `swing_trades` / `swing_signals`. Reasons:

- They're scoring scaffolding, not out-of-sample evidence
- Writing them would pollute aggregate queries on `swing_trades` with
  optimizer-fit data
- Volume is large: 7 folds × 30 grid pairs × hundreds of trades = many
  thousands of rows per WFO study

The selection metric and chosen params are persisted in
`swing_walkforward_folds.train_selection_score` and `chosen_params_json`,
which is the audit trail that matters.

### Walking up

```
swing_walkforward_runs   (1 row)
    └── swing_walkforward_folds   (2 × num_folds rows; one per role per fold)
            └── swing_strategy_runs   (1 row per fold-role)
                    ├── swing_signals
                    └── swing_trades
```

---

## 4. Code structure

### Refactor of existing code

Current `src/swing/backtest.py` has `run_backtest(strategy, keys)` which sweeps
full history. We extract a date-windowed core so walk-forward can reuse it
without duplicating bar loading / signal generation / trade pairing.

```
src/swing/backtest.py        (existing, refactored)
├─ run_backtest(strategy, keys, ...)           ← public API, unchanged signature
│       wraps _backtest_window with no date bounds + persist=True
├─ _backtest_window(strategy, keys, from_date=None, to_date=None,
│                   cost_bps_per_leg=..., capital_per_trade=...,
│                   persist=True, run_id=None)
│       ← new private core
│       ← if persist=True: creates run_id (or reuses passed-in), writes
│           swing_strategy_runs + signals + trades
│       ← if persist=False: returns (signals, trades, summary) in memory only,
│           no DB writes other than reads of market_bars_daily
└─ _load_bars(instrument_key, from_date=None, to_date=None)
        ← updated to accept date bounds; existing callers pass None/None
```

`run_backtest`'s public signature stays the same so the existing
`scripts/backtest_swing.py` keeps working.

### New module: `src/swing/walkforward.py`

```python
generate_grid() -> list[tuple[int, int]]
    # returns the 30-ish valid (fast, slow) pairs

sharpe_per_trade(trades: list[dict]) -> float | None
    # selection metric; None if undefined (<2 trades or zero stdev)

rolling_folds(
    history_start: date,
    history_end: date,
    train_window_days: int,
    test_window_days: int,
    step_days: int,
) -> Iterator[tuple[date, date, date, date]]
    # yields (train_start, train_end, test_start, test_end) per fold

run_walkforward(
    instrument_keys: list[str],
    grid: list[tuple[int, int]] | None = None,        # default: generate_grid()
    train_window_days: int = 252,
    test_window_days: int = 63,
    step_days: int = 63,
    baseline_params: tuple[int, int] = (20, 50),
    metric_fn: Callable = sharpe_per_trade,
) -> str                                              # returns wfo_id
```

Inside `run_walkforward`:

1. Determine `history_start` and `history_end` from `market_bars_daily`
   across the supplied universe (the intersection of available date ranges
   across symbols; symbols with < train_window+test_window bars are skipped
   with a warning).
2. Create the `swing_walkforward_runs` row.
3. For each fold yielded by `rolling_folds`:
   a. For each (fast, slow) in grid: instantiate `EmaCrossover(fast, slow)`,
      call `_backtest_window(strategy, keys, train_start, train_end, persist=False)`,
      compute `metric_fn(trades)`. Collect `(params, score)`.
   b. Filter out `None` scores. Pick best by max score, tie-break by
      smallest `fast + slow`. If empty after filter, emit a
      `data_health_events` warn row and `continue` to next fold.
   c. Call `_backtest_window(EmaCrossover(*winner), keys, test_start, test_end, persist=True)`
      → captures `run_id` and trade summary.
   d. Insert `swing_walkforward_folds` row with `role='optimized'`.
   e. Call `_backtest_window(EmaCrossover(*baseline_params), keys, test_start, test_end, persist=True)`.
   f. Insert `swing_walkforward_folds` row with `role='baseline'`.
4. Set `swing_walkforward_runs.status = 'complete'`.

### New script: `scripts/walkforward_swing.py`

Entry point. Loads universe from `market_bars_daily`, calls `run_walkforward`,
prints the per-fold summary table described in §5. UTF-8 stdout per the
backtest_swing precedent.

### What does NOT change

- `EmaCrossover` already accepts `fast`/`slow` via `__init__` — no
  strategy-side changes
- `swing_signals` / `swing_trades` schemas unchanged
- Cost model unchanged (7.5 bps per leg)
- Capital-per-trade unchanged (₹10,000)

---

## 5. Output

`scripts/walkforward_swing.py` prints:

```
Walk-forward complete: wfo_id=abc123...
 7 folds, 30 grid combos, baseline (20,50)

Fold  Train range              Test range               Optimized              Test net P&L   Baseline   Test net P&L
----  -----------------------  -----------------------  ---------------------  -------------  ---------  -------------
  0   2023-05-18..2024-05-17   2024-05-20..2024-08-19   (10, 60) score=0.21    ₹  12,340.55   (20, 50)   ₹   8,210.30
  1   2023-08-21..2024-08-19   2024-08-20..2024-11-19   (15, 100) score=0.15   ₹   4,109.87   (20, 50)   ₹   3,007.42
  ...

Aggregate out-of-sample:
  Optimized   total ₹  45,210.18   win-rate 0.42   sharpe-per-trade 0.18
  Baseline    total ₹  31,002.10   win-rate 0.38   sharpe-per-trade 0.14

Per-symbol out-of-sample (optimized role, sorted by net P&L):
  Symbol         Trades      Net P&L    Avg/Trade
  ----          ------    ----------    ---------
  BEL                7   ₹  9,820.15   ₹ 1,402.88
  SHRIRAMFIN         6   ₹  6,705.05   ₹ 1,117.51
  ...
  KOTAKBANK          8   ₹ -2,478.20   ₹  -309.78
```

The aggregate table answers "does optimization generalize?" — did picking-the-
best-on-train actually beat picking-once-forever? If "optimized" doesn't
materially beat "baseline" out-of-sample, the lesson is that optimization is
noise.

The per-symbol breakdown answers the strategy-centric question: **on which
stocks does this strategy actually work?** If the strategy is consistently
profitable on a subset of symbols and consistently loses on others, that's a
real signal — and it's an input to the eventual per-stock strategy
deployment pattern described in §1.5.

---

## 6. Out of scope (deliberately)

- **Per-symbol param selection inside a single WFO study.** Universe-wide
  only. The grid picks one (fast, slow) per fold across all 51 symbols. Per-
  symbol *param tuning* can be added later by promoting `chosen_params_json`
  to a per-symbol mapping; we don't pre-build for it.

  *Not* deferred: per-symbol *universes*. A strategy can already be run on a
  one-symbol universe today (see §1.5 invariant 3). You can also run this
  WFO harness with a one-symbol universe — pass `instrument_keys=[hdfcbank_key]`
  and you get walk-forward validation for a single-stock strategy. The
  harness doesn't care whether the universe is 1 or 51 symbols.
- **Multiple strategies.** Only `EmaCrossover` in this iteration. Other
  strategies will get the same harness when they exist.
- **Streamlit visualization.** Out of scope; that's roadmap item 3.
- **Intraday walk-forward.** Out of scope; intraday lane is separate.
- **Anchored windows.** Rejected in favor of rolling.
- **Sharpe with annualization / risk-free rate.** Per-trade Sharpe-like is
  enough for relative ranking; full Sharpe is overengineering for v1.
- **Statistical significance tests on optimized-vs-baseline.** Useful but
  not required for the v1 honest-baseline check.
- **Parallel grid evaluation.** Single-threaded; under a minute is fine.

---

## 7. Open questions deferred to implementation

- Whether `_backtest_window(persist=False)` should still log to
  `data_health_events` for "no bars" symbols. Probably yes, since silent
  symbol drops during optimization would distort the metric. To decide
  during implementation.
- Whether tie-breaking on (fast + slow) is the right Occam choice or if we
  should tie-break on smaller (slow). Probably the former. To decide during
  implementation.
- Exact column / header widths in the printed table. Cosmetic, to taste.
