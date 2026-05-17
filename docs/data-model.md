# Data Model

Reference for the DuckDB schema. The schema file itself
(`src/storage/schema.sql`) is the source of truth — this doc explains
*why* tables look the way they do.

For an overview of strict lane separation, see `CLAUDE.md` section 2.

---

## Shared tables

### `instruments`
Master list of tradeable instruments. Populated by backfill scripts as a
side-effect (we upsert the instruments we touch, rather than ingesting the
entire NSE master).

| Column | Type | Notes |
|---|---|---|
| `instrument_key` | VARCHAR PK | e.g. `NSE_EQ\|INE002A01018` |
| `exchange` | VARCHAR | `NSE`, `BSE` |
| `segment` | VARCHAR | `NSE_EQ`, `NSE_FO`, etc. |
| `tradingsymbol` | VARCHAR | `RELIANCE` |
| `name` | VARCHAR | full company name |
| `instrument_type` | VARCHAR | `EQ`, `FUT`, `CE`, `PE` |
| `lot_size`, `tick_size` | INTEGER, DOUBLE | nullable for cash equity |
| `updated_at` | TIMESTAMPTZ | auto |

### `market_bars_daily`
Daily OHLCV. Primary key is `(instrument_key, bar_date)`. Upserts on
re-run so corporate-action adjustments propagate.

### `market_bars_1m`
1-minute OHLCV. Same shape, with `bar_ts` as a `TIMESTAMPTZ` instead of
`DATE`. Not yet populated (will be filled by the WebSocket consumer).

---

## Swing lane tables

### `swing_strategy_runs`
One row per backtest run, paper run, or live run. Identifies a coherent
group of signals and trades.

- `run_id` — UUID
- `strategy_name`, `strategy_version` — identifies which strategy code
- `params_json` — frozen parameter values for this run
- `status` — `active` / `paused` / `retired`

### `swing_signals`
Every signal a strategy fires, **whether or not it was acted on**. This is
the dataset we use for counterfactual analysis.

- `signal_id` — UUID
- `run_id` — links to `swing_strategy_runs`
- `instrument_key`, `signal_ts`, `direction` (`LONG` / `EXIT`)
- `entry_price`, `stop_loss`, `target`
- `reasoning_json` — indicator values, conditions met, agent commentary
- `taken` — boolean, whether the signal was acted on

### `swing_trades`
Closed paper trades. Each trade pairs an entry signal with an exit signal.

- `trade_id` — UUID
- `entry_signal_id`, `exit_signal_id` — links to `swing_signals`
- `run_id`
- `instrument_key`, `direction`, `qty`
- `entry_ts`, `entry_price`, `exit_ts`, `exit_price`
- `exit_reason` — `target` / `stop` / `signal` / `manual`
- `gross_pnl`, `cost_estimate`, `net_pnl`
- `status` — `open` / `closed`

Open positions are kept with `status = 'open'`, `exit_*` fields NULL. The
backtest runner currently drops unclosed positions at the end of history.
The live paper runner (when built) will keep them open across sessions.

---

## Intraday lane tables

Mirror images of the swing tables: `intraday_strategy_runs`,
`intraday_signals`, `intraday_trades`. Same shapes, same column names.

**Why duplicate the schema instead of one set of tables with a `lane` column?**

Because the queries are always lane-scoped. A `lane` column would let
someone accidentally write a query that mixes them. The duplication
enforces the separation at the SQL layer.

The one exception is `agent_decisions`, which carries a `lane` column —
because agent calls are cross-cutting research artifacts, not trading
decisions themselves.

---

## Agent layer

### `agent_decisions`
- `decision_id` — UUID
- `lane` — `swing` or `intraday`
- `agent_role` — `generator` / `critic` / `regime` / `postmortem`
- `linked_signal_id` — optional FK into swing OR intraday signals
- `prompt`, `response` — full text
- `model`, `tokens_in`, `tokens_out` — for observability

---

## Operations

### `data_health_events`
Anything that should not have happened, but did. Backfill failures,
WebSocket disconnects, gap detections, schema migration warnings.

Severity: `info` / `warn` / `error`. Reviewed periodically; not auto-paged
in phase 1 (single user).

---

## Conventions

- Money in INR, stored as `DOUBLE`. Sufficient precision for retail amounts.
- Quantities as `INTEGER`. No fractional shares on NSE cash equity.
- Timestamps as `TIMESTAMPTZ`. The Python code uses `Asia/Kolkata` for
  display; DuckDB stores normalized.
- UUIDs as `VARCHAR` (not native UUID type, since DuckDB's UUID handling
  is uneven across drivers).
- Reasoning blobs as `VARCHAR` holding JSON. Queryable via DuckDB's JSON
  functions (`json_extract`) when needed.

---

## Useful queries

```sql
-- Latest data per symbol (sanity check after backfill)
SELECT i.tradingsymbol, MIN(b.bar_date), MAX(b.bar_date), COUNT(*)
FROM market_bars_daily b JOIN instruments i USING (instrument_key)
GROUP BY i.tradingsymbol ORDER BY 1;

-- All trades from a specific run, with reasoning
SELECT i.tradingsymbol, t.entry_ts, t.exit_ts,
       ROUND(t.net_pnl, 2) AS net,
       json_extract(s.reasoning_json, '$.trigger') AS entry_trigger
FROM swing_trades t
JOIN instruments i USING (instrument_key)
JOIN swing_signals s ON s.signal_id = t.entry_signal_id
WHERE t.run_id = '<uuid>'
ORDER BY t.entry_ts;

-- Equity curve for a run
SELECT t.exit_ts::DATE AS d,
       SUM(t.net_pnl) OVER (ORDER BY t.exit_ts) AS cum_pnl
FROM swing_trades t WHERE t.run_id = '<uuid>' ORDER BY t.exit_ts;

-- Recent data health events
SELECT * FROM data_health_events
ORDER BY event_ts DESC LIMIT 50;
```
