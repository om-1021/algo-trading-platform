# CLAUDE.md

This file is the entry point for any Claude agent (Claude Code, IDE extension,
chat) working on this project. Read it fully before making changes.

If anything here conflicts with code, **trust this file** and update the code
to match — these are the design invariants, not the current state of the repo.

---

## 1. What this project is

A personal AI-augmented algo trading platform for the Indian markets (NSE/BSE).
It is **not** a product, **not** for clients, **not** a SaaS. Single user,
single machine, single set of opinions.

The user is the sole developer and trader. All trading decisions are signals
and paper trades for now. Real money is months away.

### Phase 1 goal (current)

Build a **signal-only paper trading loop** with a complete decision audit trail
and an end-of-day dashboard. The system records:

1. **Market data** — historical and live OHLCV
2. **Strategy signals** — every fire, taken or not
3. **Paper trades** — entry, exit, P&L, costs, exit reason
4. **Agent decisions** — every LLM call with prompt and response

Phase 1 explicitly does **not** include live order placement. The Upstox
Analytics Token used by this project is read-only by design.

### Phase 2 and beyond (not started)

- Walk-forward validation, regime classification
- Live paper trading via Upstox sandbox
- Real money — small, on strategies that have survived all earlier stages
- Agent layer for strategy ideation, critique, regime tagging, cohort post-mortems

---

## 2. The non-negotiable architectural rule: strict lane separation

The platform has **two trading lanes** that share only raw market data and
must never share anything else:

| Lane | Timeframe | Style | Code namespace | Tables |
|---|---|---|---|---|
| **Swing** | Daily bars | Hold overnight, EOD decisions | `src/swing/` | `swing_*` |
| **Intraday** | 1-min bars | EOD square-off, no overnight risk | `src/intraday/` | `intraday_*` |

### What strict separation means

- `src/swing/` and `src/intraday/` **must not import from each other**.
  If a piece of logic is genuinely shared, lift it into `src/` directly or a
  new neutral package — do not cross the boundary.
- Database tables are namespaced (`swing_signals`, `intraday_signals`, etc.).
  **Never write a SQL query that JOINs a `swing_*` table with an `intraday_*`
  table.** They are independent worlds.
- The Streamlit dashboard (when built) has **separate pages** for each lane.
  No combined P&L view. No shared widgets.
- Agent decisions table has a `lane` column. Always filter by it.

The user has been explicit and emphatic about this rule. **Do not violate it
even for convenience.** Suggest a workaround if you find yourself wanting to.

### What is shared

Only these are shared between lanes:
- `instruments` table (master)
- `market_bars_daily` (raw daily OHLCV)
- `market_bars_1m` (raw 1-min OHLCV)
- `data_health_events`
- The `src/upstox/` client and `src/storage/` DB helpers
- Configuration (`config.py`)

---

## 3. Repository layout

```
.
├── CLAUDE.md                   ← you are here
├── README.md                   ← user-facing setup
├── docs/
│   ├── architecture.md         ← deeper architecture rationale
│   ├── decisions.md            ← ADR-style decision log
│   └── upstox-api-notes.md     ← API quirks, rate limits, endpoint shapes
├── .env.example
├── .gitignore
├── requirements.txt
├── config.py                   ← Settings dataclass, env loader
├── src/
│   ├── upstox/
│   │   ├── client.py           ← V3 REST wrapper for analytics token
│   │   └── instruments.py      ← instrument master loader, symbol→key
│   ├── storage/
│   │   ├── db.py               ← DuckDB connection + init_schema
│   │   └── schema.sql          ← lane-separated schema (READ THIS FIRST)
│   ├── data/
│   │   └── universe.py         ← NIFTY_50 ticker list
│   ├── swing/                  ← LANE A: daily, overnight holds
│   │   ├── base.py             ← SwingSignal, SwingStrategy ABC
│   │   ├── backtest.py         ← backtest runner with NSE cost model
│   │   └── strategies/
│   │       └── ema_crossover.py
│   ├── intraday/               ← LANE B: 1-min, EOD square-off
│   │   └── (placeholder — to be built)
│   └── agents/                 ← LLM agent layer
│       └── (placeholder — to be built)
└── scripts/
    ├── init_db.py              ← create schema (idempotent)
    ├── healthcheck.py          ← verify Upstox connectivity
    ├── backfill_daily.py       ← fetch 3y daily bars for Nifty 50
    ├── backtest_swing.py       ← run EMA crossover backtest
    └── smoke_test_swing.py     ← synthetic-data e2e test (no broker needed)
```

---

## 4. Tech stack and why

| Choice | Reason |
|---|---|
| **Python 3.11+** | Domain standard; every library we need is here |
| **DuckDB** | Single-file column-store, blazing analytical queries, zero ops |
| **Upstox V3 API (analytics token)** | User already has Upstox account; read-only token avoids order-placement risk in phase 1 |
| **pandas** | Bar manipulation, indicator math |
| **loguru** | Cleaner than stdlib logging, used everywhere |
| **requests** | Plain HTTP for Upstox; the official SDK is OAuth-focused and overkill for read-only |
| **vectorbt** (later) | Portfolio-level backtests and parameter sweeps |
| **streamlit** (later) | Local-only dashboard, fast iteration |
| **Anthropic API** (later) | Agent layer |

**Do not introduce:** ORMs (raw SQL is fine for this scale), Airflow/Prefect
(cron + scripts are enough), Docker (single-machine personal use), broker
SDKs we don't need (the official `upstox-python-sdk` works but adds OAuth
complexity we don't need for the analytics token).

---

## 5. Key design decisions

### 5.1 Why DuckDB (not SQLite, Postgres, Parquet files)
- Faster than SQLite for analytical queries (column-oriented)
- Simpler than Postgres (no server)
- Reads Parquet natively for big historical dumps later
- Single file makes backup trivial

If we ever outgrow it: migrate to Postgres + TimescaleDB. Not before.

### 5.2 Why Analytics Token (not full OAuth)
- 1-year validity, no redirect dance
- Read-only — enforces phase-1 discipline of no real trades
- All read endpoints we need are supported: historical candles V3,
  Market Data Feed V3 WebSocket, option chain + Greeks, brokerage calc,
  market status, instrument search
- See `docs/upstox-api-notes.md` for the supported endpoint list

### 5.3 Why signal-only paper trading (not Upstox sandbox)
- Sandbox adds order state machine complexity that teaches us nothing about
  strategy quality
- All phase-1 learning is about whether signals are good. Add sandbox in
  phase 2 once strategies are surviving paper.

### 5.4 Why long-only for first strategy
- Avoids short-borrow questions, stock-specific shorting rules, F&O entanglement
- Halves the state space for the audit trail
- Phase 1 is about pipeline correctness, not strategy diversity

### 5.5 Cost model
NSE delivery (cash equity, T+1 settlement) round-trip cost is approximated as
**0.075% per leg** (15 bps round-trip). Derivation in `src/swing/backtest.py`
docstring. Can be replaced with Upstox brokerage endpoint for precision.

### 5.6 Where things run
- All code runs on the user's local Windows machine, IDE = (configured via
  Claude IDE extension)
- Project root: `D:\algo-trading-platform-v2`
- DuckDB file: `D:\algo-trading-platform-v2\data\algo.duckdb`
- During market hours (09:15–15:30 IST) the machine must be awake for live
  data ingestion. VPS migration is a future consideration.

---

## 6. How an agent should work in this repo

### When asked to add a strategy
1. **Decide the lane** — daily/overnight = swing, minute-bar/EOD-squareoff = intraday
2. Add a file under `src/<lane>/strategies/<name>.py` that subclasses the
   lane's `Strategy` ABC
3. Export it from `src/<lane>/strategies/__init__.py`
4. Do **not** touch the other lane

### When asked to add a feature that touches both lanes
- Stop and ask: should this be two separate parallel implementations?
- 9 times out of 10 the answer is yes
- The one time it isn't, the code goes in a neutral location (`src/` directly
  or a new shared package), never inside `src/swing/` or `src/intraday/`

### When asked to query trade/signal data
- Filter by `run_id` to scope a specific backtest run
- Never write `JOIN swing_* WITH intraday_*`
- Use the `instruments` table for ticker symbol resolution

### When adding new tables
- Update `src/storage/schema.sql` (the file is the source of truth)
- Lane-prefix everything (`swing_xxx` or `intraday_xxx`) unless genuinely shared
- Re-run `python scripts/init_db.py` (it's idempotent — `CREATE TABLE IF NOT EXISTS`)
- For destructive migrations, write an explicit migration script under `scripts/migrations/`

### When debugging
- `loguru` is configured; use `from loguru import logger`
- For unknown failures, check `data_health_events` table — backfills log there
- The DB is a single file, so `duckdb data/algo.duckdb` opens a shell

### When in doubt about Upstox API shape
- Read `docs/upstox-api-notes.md` first
- The Upstox docs are at https://upstox.com/developer/api-documentation/
- The analytics token's supported endpoints list is in that file

---

## 7. Workflows the user runs

### First-time setup
```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env          # paste UPSTOX_ANALYTICS_TOKEN
python scripts/init_db.py
python scripts/healthcheck.py
python scripts/backfill_daily.py
```

### Daily development
- Activate venv
- Edit code
- Run smoke test: `python scripts/smoke_test_swing.py`
- Run real backtest: `python scripts/backtest_swing.py`

### When pulling fresh data
- Re-run `python scripts/backfill_daily.py` (idempotent, upserts)

---

## 8. Anti-patterns — do not do these

1. **Don't mix lanes.** Worth restating because this is the single rule the
   user will be most disappointed to find violated.
2. **Don't add live order placement.** The analytics token can't do it
   anyway, but don't sneak it in via the full OAuth flow either. Phase 1 is
   signal-only.
3. **Don't optimize parameters by running backtest, looking at result,
   adjusting params, repeating.** This is overfitting by gradient descent on
   a single sample. Walk-forward validation must be in place first
   (planned, not built).
4. **Don't trust backtest P&L as predictive.** Always present it with
   caveats: lookahead bias, regime dependence, no out-of-sample test, etc.
5. **Don't store secrets in code.** Everything goes through `config.py` and
   `.env`. `.env` is git-ignored.
6. **Don't reproduce article text or other copyrighted content** in code
   comments, READMEs, or docs.
7. **Don't introduce dependencies casually.** `requirements.txt` is short on
   purpose. Each addition needs a clear justification.

---

## 9. What's built vs. not built

### Built (phase 1, foundation)
- [x] Upstox V3 read-only client (`historical_candles`, `ltp`, `market_status`)
- [x] Instrument master loader with symbol→key mapping
- [x] DuckDB schema with strict lane separation
- [x] Nifty 50 universe definition
- [x] Daily-bar backfill script
- [x] Swing lane: `SwingSignal`, `SwingStrategy` ABC, EMA crossover, backtest runner
- [x] Smoke test on synthetic data (passes end-to-end)
- [x] Cost model for NSE delivery (0.15% round-trip)

### Not built yet
- [ ] **Walk-forward validation harness** — most important next thing
- [ ] Streamlit dashboard (swing page first, then intraday page)
- [ ] Intraday lane: WebSocket consumer for 1-min bars
- [ ] Intraday lane: Opening Range Breakout strategy
- [ ] More swing strategies (RSI mean reversion, Bollinger bands)
- [ ] Agent layer (strategy generator, critic, regime classifier)
- [ ] Live paper-trading mode (vs. backtest mode)
- [ ] Data-gap detection and automatic backfill
- [ ] Scheduler (cron jobs for EOD routines)

### Discussed but explicitly deferred
- F&O / options strategies — different architecture, phase 2+
- Real money trading — months away, requires full broker token + risk controls
- Multi-broker support — Upstox only for now
- Cloud deployment — local only for now

---

## 10. Contact between sessions

Each Claude session starts fresh. To get an agent up to speed:

1. Have it read **this file** end to end
2. Have it read `docs/architecture.md` and `docs/decisions.md`
3. Have it read `src/storage/schema.sql` so it knows the data model
4. Then describe the specific task

If something contradicts this document, **this document wins** and the code
should be updated to match. If you (the agent) believe this document is
wrong, raise it with the user before changing code on that basis.
