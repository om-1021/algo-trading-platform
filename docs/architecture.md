# Architecture

This doc explains *why* the system looks the way it does. For *what* is built,
see `CLAUDE.md` section 9.

---

## The strategy factory mental model

We are not building "an algo trading bot." We are building a **strategy
factory** — a pipeline that generates, tests, ranks, and retires strategies.

Individual trades are noise. A trade can be:
- profitable from a bad decision (got lucky)
- losing from a good decision (positive-expectancy strategy, this draw was negative)

The right unit of "learning" is therefore **cohorts of trades** for a given
strategy across regimes, not a per-trade post-mortem. Anyone who proposes
"learn from each trade and adjust" is being lured by intuition into a
well-documented retail-algo trap.

## The five-stage promotion pipeline

A strategy moves through stages, with kill criteria at each:

```
Stage 1: Hypothesis     →  written as a formal spec (entry, exit, sizing, universe)
Stage 2: Backtest       →  3–5 years of data, realistic costs, walk-forward valid
Stage 3: Walk-forward   →  rolling train/test, must show out-of-sample edge
Stage 4: Paper trade    →  live market, real frictions, 60+ trades minimum
Stage 5: Small capital  →  graduate to real money, monitor for live-vs-paper drift
```

Each stage demotes or retires strategies that fail. The system's job is to
*evaluate* strategies, not to fall in love with them.

Phase 1 of the platform builds Stages 1, 2, and 4 (skipping live paper for
now, since that requires the WebSocket consumer). Stage 3 (walk-forward) is
the most urgent next addition because without it Stage 2 results are mostly
overfit noise.

## Strict lane separation

Swing trading (daily bars, hold overnight) and intraday trading (minute bars,
EOD square-off) are architecturally different problems:

| Property | Swing | Intraday |
|---|---|---|
| Data resolution | Daily | 1-minute or finer |
| Decision cadence | EOD / pre-open | Every bar |
| Latency tolerance | Hours OK | Seconds matter |
| Overnight risk | Yes | No |
| Capital efficiency | Lower (T+1) | Higher (margin) |
| Cost as % of move | Low | High |
| Stop loss style | ATR / % | Tight, intraday-only |
| Strategy types | Trend, mean-reversion | Breakout, scalping |

Mixing them in one runtime, one P&L view, or one set of tables would obscure
problems specific to each. The user has been explicit about this: keep them
fully separated.

The shared market data tables are the exception. The raw bars are the same
underlying truth — we just consume them at different resolutions and store
strategy artifacts in lane-specific tables.

## Why DuckDB for storage

For this scale (single user, single machine, ~10–100M rows over years):

- **Column-oriented** → analytical queries 10–100x faster than SQLite for
  the kinds of aggregations we run (per-symbol P&L, equity curves, win rates)
- **Single file** → trivial backup, no DB server to manage
- **Reads Parquet natively** → easy import of bulk historical data
- **SQL standard** → no ORM lock-in, queryable from CLI for debugging
- **Embedded** → zero ops, runs in the Python process

When we outgrow it (not soon — probably never for personal use):
**Postgres + TimescaleDB** for time-series, or DuckDB + Parquet for an
analytics-only setup with a separate operational DB.

## Why local-only

A VPS / cloud setup adds: deployment scripts, secrets management in cloud,
firewall rules, monitoring. None of that is paying for itself in phase 1.
The trade-off is occasional missed WebSocket bars when the laptop sleeps.
We design the ingestion layer to be **gap-tolerant** (detect missing bars,
backfill on reconnect) rather than relying on uptime.

Migration to a VPS happens when (a) gaps become a real problem, or (b) we
start running scheduled strategies that need 24/7 reliability — neither
applies yet.

## The agent layer (planned)

LLM agents add value where conventional ML/quant systems struggle:

1. **Strategy ideation** — synthesizing papers, news, forum posts into
   formal strategy specs
2. **Strategy critique** — adversarial review of proposed strategies for
   look-ahead bias, regime dependence, overfitting risk
3. **Regime classification** — reading macro news + VIX + sectoral flows
   and tagging the current regime so strategies can be activated/deactivated
4. **Cohort post-mortems** — explaining *why* a strategy underperformed
   over a window (not per-trade)
5. **Event reasoning** — should we pause strategies before RBI policy day?
   Earnings? Election results?

The agent layer is **not the trader.** It's the research analyst. Final
strategy activation is a deterministic promotion decision based on metrics,
not an LLM call.

Every agent call is logged in `agent_decisions` with the prompt, response,
linked signal (if any), and token counts. Debuggable, reproducible,
auditable.

## What we are deliberately NOT building

- **High-frequency trading** — wrong stack, wrong infrastructure, retail
  can't compete here
- **F&O strategies (yet)** — Greeks, IV surfaces, multi-leg orders are
  their own engineering project
- **Multi-asset / global markets** — Indian equity only, scope discipline
- **Copy trading / signal selling** — single user, single account
- **A "magic" all-in-one strategy** — there isn't one; the value is in the
  factory, not any single strategy
