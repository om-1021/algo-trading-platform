# UI Design Prompt for the Algo Trading Platform

> **How to use this file:** Copy everything below the `---` line into a fresh Claude conversation (or another LLM/UI-generation tool). The recipient has no prior context, so the prompt is self-contained.

---

# Design a Next.js dashboard for a personal algo trading platform (Indian equities)

You are designing the frontend for a single-user, single-machine personal algo trading platform that trades the Indian stock market (NSE/BSE). I am the sole developer and trader. The platform is **not a SaaS, not a product for clients, not for sale**. Treat the UI as a power-user analyst tool — not a marketing site.

The backend already exists in Python with DuckDB as storage and a working walk-forward validation harness. **The backend is mostly there; you are designing the frontend that talks to it.**

---

## 1. What you are delivering

A **Next.js 14+ App Router** application in TypeScript, with:

- Tailwind CSS + **shadcn/ui** components
- **Recharts** for general charts (equity curves, bar charts, line charts)
- **TradingView lightweight-charts** for candlestick / OHLC price charts with indicator overlays
- A clean component structure, server components where applicable
- Mocked sample data inline at first (I will wire up to the real Python API afterward; you will specify the **exact API contract** each page expects so I can build matching endpoints in FastAPI)

Page set out below. For each page produce:
- The route under `app/`
- The React component file structure
- The **API contract** the page consumes (request URL + query params + response JSON shape)
- The visual layout (you may inline ASCII wireframes if helpful)

If you can ship the full project (file tree + every component implemented with mock data), do that. Otherwise prioritize the **Walk-Forward Study Detail** page (page 7 below) — that is the highest-value view and the most visually interesting.

---

## 2. Project context (so your design choices make sense)

- **The user is the sole trader.** No multi-tenancy, no auth, no permissions, no "Welcome to your dashboard." The user opens it, gets data immediately.
- **Phase 1 is signal-only paper trading.** No real money. No live order placement. The system records what the strategies *would* have done.
- **Strict lane separation:** Swing trading (daily bars, hold overnight) and Intraday trading (1-min bars, square off EOD) are architecturally independent. **They must never share UI widgets, never share a P&L view, never appear on the same page.** Use separate top-level navigation sections.
- **Strategy-centric:** Every trade in the database is tagged with the strategy that produced it. The UI must always answer "which strategy made this trade?" as a first-class question. Cross-strategy comparison is a core view.
- **Indian conventions:**
  - Currency is **INR (₹)** with Indian comma grouping (1,23,456.78 — note: ₹1 lakh = 100,000, ₹1 crore = 10,000,000; for amounts < ₹1 lakh, use plain comma grouping)
  - Timezone is **Asia/Kolkata (IST, UTC+05:30)** — display all timestamps in IST and label them
  - Market hours are 09:15–15:30 IST, Mon–Fri (NSE/BSE)
- **The platform has 51 instruments tracked** (Nifty 50 constituents + the Tata Motors successor TMCV/TMPV pair) with ~3 years of daily bars.

---

## 3. Hard constraints — non-negotiable

1. **Lane separation:** `/swing/...` and `/intraday/...` are entirely separate sections. No "combined portfolio" view. No widgets that show swing+intraday P&L together.
2. **Strategy-centric labelling everywhere:** Any trade, signal, or P&L number must show which strategy produced it. A trade row without a strategy label is broken.
3. **No fabricated content:** No marketing copy, no motivational text, no emojis in the UI, no fake "AI insights" that aren't backed by actual computation. If a number is computed, show it; if not, don't pretend.
4. **No real-money implications:** Never show "your portfolio is worth X" without context. Always show: which strategy, which time period, paper vs (future) real. Phase 1 is paper-only.
5. **Information density over aesthetic minimalism:** This is a power-user tool. Pack data into the viewport. Long tables are fine. Generous whitespace and big hero text are not appropriate for an analyst dashboard.
6. **Dark mode is the default.** Light mode toggle is optional. Trading dashboards live in dark mode.
7. **Currency formatting:** Always use Indian-style comma grouping for INR. Don't use $ anywhere. Don't use European-style 1.234,56.
8. **Backtest P&L is not predictive.** Anywhere you show backtest results, include a small "Backtest only — past returns do not predict future returns" tag. This applies to the entire swing strategy runs view and walk-forward results view. **The user has been emphatic about this.**

---

## 4. Sitemap (top-level navigation)

```
Home (overview)
├─ Universe          (master list of instruments + data coverage)
├─ Swing
│  ├─ Strategies     (list of all swing strategies + aggregate perf)
│  ├─ Strategy Runs  (list of swing_strategy_runs)
│  ├─ Walk-Forward   (list of WFO studies)
│  └─ Signals        (counterfactual: every signal, taken or not)
├─ Intraday          (placeholder — see §6.10 below)
├─ Live              (placeholder — see §6.11 below)
└─ Data Health       (data_health_events viewer)
```

Two top-level tabs in the layout: **EOD Analysis** (default, primary) and **Live Monitoring** (secondary, placeholder for now). Switching the tab swaps the main content area but keeps the same sidebar nav.

---

## 5. Tech stack & dependencies you should propose

```jsonc
// package.json key deps
{
  "next": "^14.x",
  "react": "^18.x",
  "typescript": "^5.x",
  "tailwindcss": "^3.x",
  "@radix-ui/* via shadcn/ui": "latest",
  "recharts": "^2.x",
  "lightweight-charts": "^4.x",       // TradingView's candlestick lib
  "date-fns": "^3.x",
  "date-fns-tz": "^2.x",              // for IST formatting
  "lucide-react": "^0.x",             // icons
  "@tanstack/react-table": "^8.x",    // for the big trade tables
  "@tanstack/react-query": "^5.x"     // for API caching
}
```

You may add to this list if needed, but justify each addition.

---

## 6. Page specifications

### 6.1 — Home / Overview

**Route:** `/`

**Purpose:** Snapshot of the entire platform state at a glance. The first thing the user sees after opening the app.

**Sections (top to bottom):**

1. **Status strip (4 KPI cards in one row):**
   - "Universe" — N instruments tracked, with sub-text "last bar: 2026-05-15"
   - "Active swing strategies" — count + sub-text "X total runs"
   - "Walk-forward studies" — count + sub-text "Y complete, Z failed"
   - "Latest WFO outcome" — net P&L of latest WFO optimized role, color-coded green/red, with the wfo_id (truncated UUID, monospaced)

2. **Recent activity feed** (left column, ~60% width):
   - Reverse-chronological list of events from the last 7 days
   - Event types: "WFO study b86a88f2 completed", "Backtest run 8b952417 finished — 44 trades", "Backfill: 743 bars added for SBILIFE", "Data health: warn (component=backfill, ...)"
   - Each row clickable → relevant detail page

3. **Universe data freshness** (right column, ~40% width):
   - Sparkline + color-coded chip per instrument: green if data current to last trading day, amber if 1-3 days stale, red if >3 days stale
   - Compact view; shows first 10 instruments, "+ 41 more" link

4. **Footer with version metadata:** `algo-trading-platform v0.1 · IST · DuckDB at ./data/algo.duckdb`

**API contracts:**
- `GET /api/overview/kpis` → `{ universe_count, latest_bar_date, active_strategies, total_runs, wfo_studies_complete, wfo_studies_failed, latest_wfo: { wfo_id, optimized_net_pnl, completed_at } }`
- `GET /api/overview/activity?since=ISO_DATE` → `[{ event_id, event_ts, event_type, message, target_url }]`
- `GET /api/universe/freshness` → `[{ tradingsymbol, last_bar_date, days_stale, last_30_closes: [float] }]`

---

### 6.2 — Universe

**Route:** `/universe`

**Purpose:** Browse the 51 tracked instruments. Drill into per-instrument detail.

**Layout:**

- Search box (filter by tradingsymbol or name)
- Filters: data coverage status (all / current / stale / very stale)
- **Table** (sortable on every column):

| Column | Type | Notes |
|---|---|---|
| tradingsymbol | text | monospaced, e.g. `RELIANCE` |
| name | text | "Reliance Industries Limited" |
| instrument_key | text | small, monospaced, e.g. `NSE_EQ\|INE002A01018` |
| first_bar | date | earliest bar in our DB |
| last_bar | date | latest bar |
| total_bars | int | comma-formatted |
| 30-day sparkline | inline chart | last 30 closes |
| total trades | int | across all strategies — clickable filter to strategy runs |

- Row click → `/universe/[tradingsymbol]`

**API:** `GET /api/universe` → `[{ tradingsymbol, name, instrument_key, first_bar, last_bar, total_bars, last_30_closes: [float], total_trades }]`

---

### 6.3 — Universe / Instrument Detail

**Route:** `/universe/[tradingsymbol]`

**Purpose:** Everything we know about one instrument.

**Sections:**

1. **Header card:**
   - Symbol + full name + instrument_key
   - Latest close + day's change %
   - Data coverage: "743 bars, 2023-05-18 → 2026-05-15"

2. **Price chart** (TradingView lightweight-charts, ~60% of viewport height):
   - Candlestick by default
   - Toggleable timeframe: 1Y / 3Y / All
   - Toggleable indicator overlays: EMA-20, EMA-50, EMA-200, Bollinger Bands (these compute client-side from OHLC)
   - **Markers** for every trade entry/exit on this symbol across all strategies (green up arrow = LONG entry, red down arrow = exit). Hovering a marker shows: strategy, run_id (short), entry/exit price, net P&L
   - Each marker color-keyed by strategy when multiple strategies exist

3. **Per-strategy performance** (table below chart):
   - One row per strategy that has traded this symbol
   - Columns: strategy_name, n_trades, win_rate, total_net_pnl, avg_pnl_per_trade, best, worst

4. **Recent trades** (table):
   - Reverse-chronological, paginated
   - Columns: entry_ts (IST), exit_ts, entry_price, exit_price, qty, gross_pnl, cost, net_pnl, strategy, run_id (truncated)
   - Click row → trade detail modal/page

**API:**
- `GET /api/instruments/[tradingsymbol]` → metadata + coverage
- `GET /api/instruments/[tradingsymbol]/bars?from=&to=` → OHLCV array
- `GET /api/instruments/[tradingsymbol]/trades?strategy=&from=&to=` → trade list with strategy join
- `GET /api/instruments/[tradingsymbol]/markers` → `[{ ts, type: "entry"|"exit", direction: "LONG", price, strategy, run_id, trade_id, net_pnl }]`

---

### 6.4 — Swing / Strategies

**Route:** `/swing/strategies`

**Purpose:** Top-level list of all swing strategies. Card per strategy.

**Layout:**

- Grid of strategy cards (2-3 columns on desktop)
- Each card:
  - Strategy name (e.g. `ema_crossover`)
  - Latest version
  - Mini equity curve sparkline (cumulative net_pnl across all runs)
  - 3 metric chips: total trades, total net P&L, win rate
  - "Latest run: 2 hours ago" timestamp
  - Click → `/swing/strategies/[strategy_name]`

Currently only one strategy exists (`ema_crossover`). Design must accommodate future additions (`rsi_meanrev`, `bollinger_breakout`, etc.) without re-layout.

**API:** `GET /api/swing/strategies` → `[{ strategy_name, latest_version, total_runs, total_trades, win_rate, total_net_pnl, latest_run_at, equity_curve_points: [{ts, cum_pnl}] }]`

---

### 6.5 — Swing / Strategy Runs

**Route:** `/swing/runs`

**Purpose:** List every `swing_strategy_runs` row with filters and search.

**Layout:**

- Filter chips along the top: strategy, status (active/paused/retired), date range, role (linked to WFO: optimized / baseline / standalone)
- Search box: paste a run_id (truncated UUID matching)
- **Sortable table:**

| Column | Notes |
|---|---|
| run_id | truncated to 8 chars, monospaced, with copy-to-clipboard icon |
| strategy_name + version | |
| started_at | IST formatted |
| status | colored badge (green=active, amber=paused, gray=retired) |
| linked WFO | wfo_id truncated, or "standalone" if not WFO-linked |
| role | "optimized" / "baseline" / "—" |
| params | inline json mini-table, e.g. `fast=10 slow=30` |
| n_trades | int |
| net P&L | color-coded |
| win rate | percentage |

- Row click → `/swing/runs/[run_id]`

**API:** `GET /api/swing/runs?strategy=&status=&from=&to=` → `[{ run_id, strategy_name, strategy_version, params, started_at, status, wfo_id, role, n_trades, net_pnl, win_rate }]`

---

### 6.6 — Swing / Strategy Run Detail

**Route:** `/swing/runs/[run_id]`

**Purpose:** Everything about a single backtest or test-window run.

**Sections (top to bottom):**

1. **Header strip:**
   - Run id (full UUID + copy button)
   - Strategy name, version, params (e.g. `fast=10 slow=30`)
   - Started timestamp (IST)
   - Status badge
   - If linked to WFO: "Part of WFO study `b86a88f2...` · Fold 0 · Optimized role" — clickable

2. **KPI strip** (6 cards):
   - Trades · Wins · Losses · Win rate · Total net P&L · Sharpe-per-trade

3. **Equity curve** (Recharts):
   - X-axis: trade exit timestamp (IST)
   - Y-axis: cumulative net P&L in ₹
   - Shaded drawdown regions
   - Hover tooltip shows: date, cumulative P&L, trade that caused this step (symbol)

4. **Per-symbol breakdown** (sortable table):
   - Columns: tradingsymbol, n_trades, total_net, avg_pnl, win_rate, best_trade, worst_trade
   - Mini-sparkline column: per-trade P&L sequence
   - Sort by net P&L descending by default
   - Row click → instrument detail page filtered to this run

5. **Trade list** (paginated table, ~50 rows per page):
   - Columns: trade_id (truncated), tradingsymbol, direction, entry_ts, exit_ts, entry_price, exit_price, qty, gross_pnl, cost, net_pnl, exit_reason
   - Color-coded P&L
   - Row click → trade detail modal

6. **Signal log toggle:**
   - Tab: "Trades (44)" / "Signals (88)" — switch view to all signals (entries + exits) including ones not paired into trades
   - Signal-only view shows the `reasoning_json` blob inline (pretty-printed, collapsible)

**Backtest disclaimer banner:** at the bottom of the page (or top, your call) — "Backtest results. Past performance does not predict future returns."

**API:**
- `GET /api/swing/runs/[run_id]` → run metadata + KPIs
- `GET /api/swing/runs/[run_id]/equity-curve` → `[{ exit_ts, cum_pnl, trade_id, tradingsymbol }]`
- `GET /api/swing/runs/[run_id]/per-symbol` → per-symbol aggregation
- `GET /api/swing/runs/[run_id]/trades?page=&per_page=` → paginated trades
- `GET /api/swing/runs/[run_id]/signals?page=&per_page=` → paginated signals

---

### 6.7 — Swing / Walk-Forward Studies (THE BIG ONE)

**Route list:** `/swing/walkforward`

Lists all `swing_walkforward_runs`. Each card shows: wfo_id (truncated), strategy, window config (e.g. "252/63/63"), status badge, optimized vs baseline aggregate P&L comparison mini-bar, started_at. Click → detail.

**Route detail:** `/swing/walkforward/[wfo_id]`

This is the **highest-value, most visually interesting page** in the dashboard. Treat it as the showpiece.

**Sections (top to bottom):**

#### Section A — Study header

- Study metadata: strategy_name, train/test/step config, selection_metric, baseline_params, started_at, status
- The full param grid: rendered as a small grid of pills (42 pills) — non-interactive, just shows what was searched

#### Section B — Headline aggregate comparison (2 large cards side-by-side)

- Left card: **Optimized** role
  - Big number: total net P&L (color-coded)
  - Sub-stats: n_trades · win_rate · sharpe-per-trade
- Right card: **Baseline (20, 50)** role
  - Same layout
- Below both: a small **Δ comparison strip** — "Optimized is ₹X worse than baseline" or "Optimized is ₹Y better than baseline" with arrow

This is where the user immediately sees: did optimization help, or did the strategy not generalize?

#### Section C — Fold timeline strip (NEW visualization)

A horizontal timeline along a date axis showing all folds:
- Each fold rendered as two stacked rectangles: train (lighter) and test (darker)
- Label above each fold: fold index + chosen optimized params (e.g. `Fold 0: (10,30)`)
- Color the test rectangle by net P&L of the optimized role for that fold (green/red gradient)
- Below each test rectangle: a small number — the net P&L
- This gives an instant "where did it work and where did it fail" view across calendar time

#### Section D — Per-fold table (optimized vs baseline side-by-side)

| Fold | Train range | Test range | Optimized params | Train score | Opt test P&L | Opt win rate | Baseline test P&L | Baseline win rate | Δ |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 2023-05-18..2024-05-22 | 2024-05-23..2024-08-22 | (10, 30) | 0.335 | ₹-13,321.89 | 18.2% | ₹-11,945.95 | 18.2% | -₹1,375.94 |
| ... | | | | | | | | | |

- Sortable on every column
- Row click → expand inline to show per-symbol breakdown for that fold's optimized role

#### Section E — Train-score degradation line chart

This is the most important visual on the page:
- X-axis: fold index (0..6)
- Y-axis: train_selection_score
- Line with markers at each fold
- Reference line at 0 (the "no signal" threshold)
- If the line trends downward over folds (which it does in your data: 0.335 → 0.312 → 0.335 → 0.061 → -0.099 → -0.196 → -0.095), that visually conveys "the strategy degraded over time — the optimizer was learning noise in early folds and the noise didn't repeat"
- Annotation callout: "Train score crossed 0 at fold 4 — strategy stopped having edge on the train window"

#### Section F — Cumulative out-of-sample equity curves (overlay chart)

Two lines on one chart:
- Optimized cumulative P&L over test-window calendar dates
- Baseline cumulative P&L over the same dates
- Both starting from 0 at the first test_start
- Shaded fold boundaries as vertical lines

This visually answers "did picking-best-on-train track-out-of-sample beat picking-once-forever?"

#### Section G — Per-symbol heatmap (TWO heatmaps, one per role)

Rows = tradingsymbols (sorted by total optimized P&L descending)
Columns = fold indices 0..6
Cell color = net P&L for that symbol in that fold's test window (green/red gradient, with intensity by magnitude)
Cell tooltip: exact P&L, trade count, win rate

This is where the user spots: "is there any symbol where this strategy consistently worked across folds?" In your data the answer will be no — but that's the finding.

#### Section H — Per-symbol summary (sortable table, top 10 and bottom 10)

Optimized role only:
- Columns: tradingsymbol, total_trades, total_net_pnl, avg_pnl, win_rate
- Sort by net P&L
- Show top 10 and bottom 10 with a "show all 47" expand

#### Footer

Backtest disclaimer + "Strategy-centric query: see [link to /swing/runs?wfo_id=...]"

**API for this page (the largest set):**
- `GET /api/swing/walkforward/[wfo_id]` → metadata
- `GET /api/swing/walkforward/[wfo_id]/folds` → all fold rows joined with their test_summary_json parsed
- `GET /api/swing/walkforward/[wfo_id]/equity-curves?role=` → cumulative P&L by date for one role
- `GET /api/swing/walkforward/[wfo_id]/heatmap?role=` → per-symbol-per-fold matrix
- `GET /api/swing/walkforward/[wfo_id]/per-symbol?role=` → aggregated per-symbol stats

---

### 6.8 — Swing / Signals (counterfactual)

**Route:** `/swing/signals`

**Purpose:** Browse every signal ever generated — taken or not-taken. Helps assess whether the *strategy* is correct independent of whether we acted on it.

**Layout:**

- Filters: strategy, symbol, direction (LONG/EXIT), taken (yes/no/all), date range
- Table:

| Column | Notes |
|---|---|
| signal_id | truncated |
| strategy | |
| tradingsymbol | |
| signal_ts | IST |
| direction | LONG / EXIT (badged) |
| entry_price | |
| reasoning | small "view" button → modal with full reasoning_json pretty-printed |
| taken | green dot if true, red dot if false |
| trade_id | (if taken) clickable to trade detail |

- Row click → expand reasoning_json + show "if we had taken this LONG, the next EXIT would have produced X" counterfactual

**API:** `GET /api/swing/signals?strategy=&symbol=&taken=&from=&to=&page=` → paginated

---

### 6.9 — Trade detail (modal or page)

**Route:** `/swing/trades/[trade_id]` (or modal overlay; you choose)

**Purpose:** Forensic deep-dive on one trade. "Why did we make this trade? What did we see at the moment of decision?"

**Layout:**

1. **Header:** instrument name + symbol, direction (LONG), strategy, run_id linkable

2. **Price chart focused on the entry-exit window** (TradingView lightweight-charts):
   - Show ~30 bars before entry, the entry-to-exit window, ~10 bars after exit
   - Indicator overlays: whichever indicators are in the entry signal's reasoning_json (e.g. for ema_crossover: EMA-fast and EMA-slow at the run's chosen periods)
   - Entry marker (green up arrow at exact entry_ts and entry_price)
   - Exit marker (red down arrow at exact exit_ts and exit_price)
   - P&L delta annotation

3. **At-entry context** (table):
   - All indicator values from `reasoning_json` at signal time
   - Bar OHLCV at entry
   - Day-of-week, days since last signal on this symbol

4. **Costs breakdown** (small table):
   - Gross P&L
   - Brokerage estimate
   - STT estimate
   - Exchange charges
   - GST
   - Stamp duty (buy leg)
   - Net P&L
   - These breakdowns aren't currently stored per-trade but are derivable from `cost_estimate` total — display the total and label the breakdown as "approximate, see backtest.py docstring"

5. **Reasoning JSON** (expandable, pretty-printed)

**API:**
- `GET /api/trades/[trade_id]` → trade with joined run, instrument, both signals' reasoning_json
- `GET /api/instruments/[tradingsymbol]/bars-window?center_ts=&before=30&after=10` → focused OHLCV window

---

### 6.10 — Intraday section (placeholder)

**Routes:** `/intraday/...`

The intraday lane is **not built yet** in the backend (no WebSocket consumer, no minute-bar ingestion). The UI should:

- Show the navigation entries (Strategies, Strategy Runs, etc.) so the structure is visible
- Each route renders a placeholder page with:
  - A clear "Coming in Phase 2 — Intraday lane (1-min bars, EOD square-off) is on the roadmap" banner
  - A small description of what will go here
  - **Crucially: no shared UI components with the swing pages.** The placeholders are intraday-specific even though they're empty. Do not "fall back" to swing data.

**Routes to scaffold (all placeholder):**
- `/intraday/strategies`
- `/intraday/runs`
- `/intraday/signals`

---

### 6.11 — Live monitoring tab (placeholder, secondary tab)

**Route:** `/live` (and child routes if you want)

**Purpose:** Real-time monitoring during market hours. **Most of the data this would show doesn't exist yet** — the WebSocket consumer is roadmap item 7. Build the UI shell now so it's ready when the data lands.

**Layout (all sections show empty-states):**

1. **Market status strip:**
   - "Market: OPEN (closes in 2h 14m)" or "CLOSED" based on time of day
   - Today's date (IST)
   - NSE/BSE both shown if relevant
   - This DOES exist: poll `/api/market-status` (we have a market status endpoint on the Upstox client)

2. **Today's open positions:**
   - Empty table for now, columns: symbol, strategy, qty, entry_price, current_price, MTM P&L, unrealized P&L %
   - Empty-state copy: "No positions open. Live paper trading begins when the EOD scheduler is built."

3. **Today's signal stream:**
   - Live-updating list (would use Server-Sent Events when wired up)
   - Empty state for now

4. **Today's P&L:**
   - Strategy filter
   - Bar chart of realized + unrealized P&L
   - Empty state

5. **Active strategies pulse:**
   - List of strategies in `active` status, with last-evaluation timestamp
   - Empty for now

**API:**
- `GET /api/market-status` (returns `{ status: "open"|"closed", next_close_ist?, next_open_ist? }`) — this one is real
- Others are stubs to be wired up later

---

### 6.12 — Data Health

**Route:** `/data-health`

**Purpose:** Browse `data_health_events`. Silent failures are the worst — this view surfaces them.

**Layout:**

- Filters: severity (info / warn / error), component (backfill / ws_feed / scheduler / walkforward), date range
- Search box: free-text on `message`
- Table:

| Column | Notes |
|---|---|
| event_ts | IST |
| severity | colored badge |
| component | small pill |
| message | text, can wrap |
| context_json | "view" button → modal pretty-print |

- Row click → expand with full context

**API:** `GET /api/data-health?severity=&component=&from=&to=&q=` → paginated rows

---

## 7. Data shapes — real sample rows from the DB

Use these to design realistic mocks. Every shape below is verbatim from the running database (some long fields truncated for readability).

### 7.1 — `swing_walkforward_runs` row (a "study")

```json
{
  "wfo_id": "b86a88f2-83ba-4649-b5da-7be3d0df48ea",
  "strategy_name": "ema_crossover",
  "param_grid_json": "[[5,30],[5,40],[5,50],[5,60],[5,100],[5,200],[8,30],[8,40],[8,50],[8,60],[8,100],[8,200],[10,30],[10,40],[10,50],[10,60],[10,100],[10,200],[13,30],[13,40],[13,50],[13,60],[13,100],[13,200],[15,30],[15,40],[15,50],[15,60],[15,100],[15,200],[20,30],[20,40],[20,50],[20,60],[20,100],[20,200],[25,30],[25,40],[25,50],[25,60],[25,100],[25,200]]",
  "train_window_days": 252,
  "test_window_days": 63,
  "step_days": 63,
  "selection_metric": "sharpe_per_trade",
  "baseline_params_json": "{\"fast\": 20, \"slow\": 50}",
  "started_at": "2026-05-18T02:05:41.309005+05:30",
  "status": "complete"
}
```

### 7.2 — `swing_walkforward_folds` row (one fold, optimized role)

```json
{
  "fold_id": "c0588acb-5201-48e8-9731-843c557fef38",
  "wfo_id": "b86a88f2-83ba-4649-b5da-7be3d0df48ea",
  "fold_index": 0,
  "train_start": "2023-05-18",
  "train_end": "2024-05-22",
  "test_start": "2024-05-23",
  "test_end": "2024-08-22",
  "role": "optimized",
  "chosen_params_json": "{\"fast\": 10, \"slow\": 30}",
  "train_selection_score": 0.3353038464360686,
  "test_run_id": "8b952417-28f6-4a7f-9502-43b8775e5bd5",
  "test_summary_json": "{\"run_id\":\"8b952417-28f6-4a7f-9502-43b8775e5bd5\",\"trades\":44,\"wins\":8,\"losses\":36,\"win_rate\":0.1818,\"total_net_pnl\":-13321.89,\"avg_trade_pnl\":-302.77,\"best_trade\":372.26,\"worst_trade\":-2022.75,\"sharpe_per_trade\":-0.677}"
}
```

### 7.3 — `swing_strategy_runs` row

```json
{
  "run_id": "8b952417-28f6-4a7f-9502-43b8775e5bd5",
  "strategy_name": "ema_crossover",
  "strategy_version": "1.0",
  "params_json": "{\"fast\": 10, \"slow\": 30}",
  "started_at": "2026-05-18T02:06:12.000000+05:30",
  "status": "active"
}
```

### 7.4 — `swing_trades` row

```json
{
  "trade_id": "ba7d424f-4c12-4a75-b0e5-06cee1be86ff",
  "entry_signal_id": "748ee289-d037-4f8a-a7b5-bb80e82a72ca",
  "exit_signal_id": "fc79a278-1442-437b-b689-3ad1edb22d70",
  "run_id": "8b952417-28f6-4a7f-9502-43b8775e5bd5",
  "instrument_key": "NSE_EQ|INE002A01018",
  "direction": "LONG",
  "qty": 6,
  "entry_ts": "2024-06-26T15:30:00+05:30",
  "entry_price": 1514.0,
  "exit_ts": "2024-07-26T15:30:00+05:30",
  "exit_price": 1509.0,
  "exit_reason": "signal",
  "gross_pnl": -30.0,
  "cost_estimate": 13.6035,
  "net_pnl": -43.6035,
  "status": "closed"
}
```

### 7.5 — `swing_signals` row with reasoning

```json
{
  "signal_id": "748ee289-d037-4f8a-a7b5-bb80e82a72ca",
  "run_id": "8b952417-28f6-4a7f-9502-43b8775e5bd5",
  "instrument_key": "NSE_EQ|INE002A01018",
  "signal_ts": "2024-06-26T15:30:00+05:30",
  "direction": "LONG",
  "entry_price": 1514.0,
  "stop_loss": null,
  "target": null,
  "reasoning_json": "{\"trigger\":\"ema_fast_crossed_above_ema_slow\",\"ema_fast\":1468.55,\"ema_slow\":1467.03,\"fast_period\":10,\"slow_period\":30}",
  "taken": true
}
```

### 7.6 — `instruments` row

```json
{
  "instrument_key": "NSE_EQ|INE002A01018",
  "exchange": "NSE",
  "segment": "NSE_EQ",
  "tradingsymbol": "RELIANCE",
  "name": "RELIANCE",
  "instrument_type": "EQ",
  "lot_size": null,
  "tick_size": null,
  "updated_at": "2026-05-17T22:00:00+05:30"
}
```

### 7.7 — `market_bars_daily` row

```json
{
  "instrument_key": "NSE_EQ|INE002A01018",
  "bar_date": "2024-06-26",
  "open": 1500.0,
  "high": 1520.0,
  "low": 1495.0,
  "close": 1514.0,
  "volume": 9500000,
  "open_interest": 0
}
```

### 7.8 — Aggregate optimized vs baseline for the latest WFO study

```json
{
  "optimized": { "n_trades": 331, "total_net_pnl": -95114.74, "win_rate": 0.0937 },
  "baseline":  { "n_trades": 208, "total_net_pnl": -88563.93, "win_rate": 0.0192 }
}
```

### 7.9 — Per-fold time series (the data behind the train-score degradation chart)

```json
[
  { "fold_index": 0, "test_start": "2024-05-23", "chosen_params": [10,30], "train_score":  0.335, "opt_net_pnl": -13321.89, "base_net_pnl": -11945.95 },
  { "fold_index": 1, "test_start": "2024-08-23", "chosen_params": [15,30], "train_score":  0.312, "opt_net_pnl": -14320.03, "base_net_pnl": -14398.73 },
  { "fold_index": 2, "test_start": "2024-11-25", "chosen_params": [25,30], "train_score":  0.335, "opt_net_pnl": -17795.55, "base_net_pnl": -17844.71 },
  { "fold_index": 3, "test_start": "2025-02-20", "chosen_params": [ 8,50], "train_score":  0.061, "opt_net_pnl": -11694.00, "base_net_pnl":  -7270.84 },
  { "fold_index": 4, "test_start": "2025-05-29", "chosen_params": [ 8,30], "train_score": -0.099, "opt_net_pnl": -15889.59, "base_net_pnl": -17454.74 },
  { "fold_index": 5, "test_start": "2025-08-28", "chosen_params": [ 5,30], "train_score": -0.196, "opt_net_pnl":  -9624.55, "base_net_pnl": -13953.42 },
  { "fold_index": 6, "test_start": "2025-11-28", "chosen_params": [ 8,30], "train_score": -0.095, "opt_net_pnl": -12469.14, "base_net_pnl":  -5695.54 }
]
```

---

## 8. Visual style guidance

- **Dark mode by default.** Background #0b0d10 or similar near-black. Cards on #14171a. Text on #e6e8ea.
- **Accent colors:** Green for positive P&L / "active" / wins (#22c55e or similar). Red for losses / errors (#ef4444). Amber for warnings (#f59e0b). Subtle blue/violet for neutral chips/badges.
- **Font:** Inter (or system sans) for general text. **JetBrains Mono / IBM Plex Mono** for: UUIDs, instrument_keys, params, prices, P&L numbers, anything tabular and numeric.
- **Numeric formatting:**
  - INR with Indian comma grouping: `₹1,23,456.78`
  - Percentages to 1 decimal: `37.5%`
  - UUIDs displayed truncated to 8 chars + ellipsis, with copy-to-clipboard on hover: `b86a88f2…`
  - Timestamps: `2026-05-18 02:05 IST` (short form for tables, full `2026-05-18T02:05:41+05:30` in tooltips)
- **Information density:** Use 12–13px base font for tables. Tight row heights. Sticky table headers when scrolling.
- **Cards should not have shadows.** Use 1px borders in the next-darker shade. This isn't an iOS app.
- **No animations beyond functional micro-interactions** (hover state, sort indicator, dropdown open). No page transitions, no entrance animations, no parallax.
- **Sidebar nav:** persistent, ~220px wide. Collapsible to icon-only.

---

## 9. Currency, time, and label conventions (apply everywhere)

| Concept | Example | Rule |
|---|---|---|
| INR positive | `₹1,23,456.78` | Indian comma grouping, ₹ prefix, no space |
| INR negative | `−₹1,23,456.78` | Use minus sign (−) not hyphen, color red |
| Percentage | `37.5%` | One decimal, % suffix |
| Win rate | `8 / 44 (18.2%)` | Show both fraction and pct |
| Timestamp short | `2026-05-18 02:05` | YYYY-MM-DD HH:mm, IST implied if column is labeled "IST" |
| Timestamp full | `2026-05-18T02:05:41+05:30` | ISO 8601 with offset (in tooltips) |
| UUID display | `b86a88f2…` | 8 char + ellipsis, monospace, copy on hover |
| Instrument key | `NSE_EQ\|INE002A01018` | Show full in tables, monospaced |
| Symbol | `RELIANCE` | Uppercase, monospaced |
| Strategy name | `ema_crossover` | snake_case as stored, monospaced or chip-styled |

---

## 10. Anti-patterns to avoid

1. **No mixing swing and intraday in a single view** — even in the home overview, do not aggregate cross-lane numbers
2. **No backtest results without a disclaimer** — small but visible "Backtest only — past returns do not predict future returns" on every page that shows backtest P&L
3. **No fabricated "AI insight" text** — don't add summaries that aren't actual computed results
4. **No emojis** in any persistent UI text
5. **No marketing-style hero copy** — no "Welcome", no "Get started", no taglines
6. **No big number summaries without strategy attribution** — a giant ₹95,114 number is meaningless without knowing it's the optimized WFO outcome
7. **No US dollar conversions, no "$" anywhere** — INR only
8. **No "your account" framing** — this is the user's tool, not a customer dashboard
9. **No fake live data** — the live monitoring tab is mostly placeholder for now; clearly state what's not yet built
10. **No social features** — no avatars, no comments, no notifications panel beyond data health events

---

## 11. Deliverables I want from you

1. A complete Next.js 14 App Router project, ready to `npm install && npm run dev`
2. TypeScript throughout, with proper types for all the API contracts above
3. shadcn/ui setup done, Tailwind configured for dark mode default
4. All pages implemented with realistic mock data inline (use the sample shapes from §7 as the basis)
5. Every API contract documented in `lib/api-types.ts` (TypeScript types for request and response of every endpoint)
6. A `MOCK_DATA.md` file documenting which mock data lives where, so I can swap it for real API calls
7. README explaining the architecture, how to run, where to plug in the real API
8. Particular care on the **Walk-Forward Study Detail page (§6.7)** — this is the showpiece

If you must defer some pages, do them in this priority order:
1. Walk-Forward Study Detail (`/swing/walkforward/[wfo_id]`) — must be polished
2. Home (`/`) — must be informative
3. Strategy Run Detail (`/swing/runs/[run_id]`) — must support drill-in
4. Trade Detail (`/swing/trades/[trade_id]`) — modal is fine
5. Walk-Forward list, Strategy Runs list, Strategies list
6. Universe + instrument detail
7. Signals counterfactual page
8. Data Health
9. Live tab (mostly placeholder)
10. Intraday placeholders

Output the entire file tree. Output every file's contents inline. Use markdown code fences with the file path as the language tag.

If you have any clarifying questions before generating, ask them first.

---

**End of prompt.**
