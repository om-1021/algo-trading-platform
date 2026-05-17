# Decision Log

Append-only record of significant decisions. Newest first. When reversing a
decision, add a new entry referencing the old one — don't edit history.

Format: ADR (Architecture Decision Record) — Context, Decision, Consequences.

---

## ADR-008 — 2026-05: First strategy is EMA 20/50 crossover, long-only

**Context.** Need a first strategy to drive the pipeline. Could pick anything.

**Decision.** EMA 20/50 crossover, long-only, no stop, no target. Always-in-
or-out.

**Consequences.** Strategy will lose money in chop, make money in trends.
This is a known property — we are validating the *pipeline*, not the strategy.
Performance numbers from this strategy are not predictive of anything. Two
better strategies are queued next: RSI mean-reversion and Bollinger bands.

---

## ADR-007 — 2026-05: Cost model approximation: 7.5 bps per leg

**Context.** NSE delivery costs (brokerage, STT, exchange, GST, stamp, DP) are
fragmented across many tiny line items. Computing each precisely per trade
is doable but adds complexity.

**Decision.** Approximate at 0.075% per leg (15 bps round-trip). Configurable
via parameter. Upstox's brokerage endpoint can replace this when precision
matters.

**Consequences.** Backtest costs are within ~10–20% of reality for typical
retail trade sizes (₹5k–₹50k notional). Underestimates costs for very small
trades (where ₹20 flat brokerage dominates). Acceptable for phase 1.

---

## ADR-006 — 2026-05: Universe scope: Nifty 50 cash equity only

**Context.** "Test all the trades" instinct vs. focused scope.

**Decision.** Start with Nifty 50 cash equity. Expand to Nifty 200, F&O,
options, and intraday-specific universes later. Never go to "all NSE
equities" without a specific reason.

**Consequences.** ~50 instruments × ~750 trading days × 3 years = ~37k daily
bars. Manageable storage, fast queries, liquid instruments, low slippage.
Avoids penny-stock anomalies. Limits strategy diversity until we expand.

---

## ADR-005 — 2026-05: Signal-only paper trading for phase 1

**Context.** Could use Upstox sandbox for paper orders, or pure simulation.

**Decision.** Pure simulation. Strategies emit signals; the paper engine
simulates outcomes from those signals using market data.

**Consequences.** Skips order state machine complexity. Doesn't catch
real-world frictions (bad fills, queue position, partial executions, API
errors). Acceptable for phase 1 — those frictions only matter once strategies
have edge worth defending. Add sandbox in phase 2.

---

## ADR-004 — 2026-05: Strict lane separation (swing vs intraday)

**Context.** Swing and intraday could share a strategy ABC, a unified P&L
view, a single dashboard.

**Decision.** They do not. Separate packages (`src/swing/`, `src/intraday/`),
separate tables (`swing_*`, `intraday_*`), separate dashboard pages, no
cross-imports. Shared: only raw market data tables and infrastructure
(Upstox client, DuckDB connection, config).

**Consequences.** Some apparent duplication (each lane has its own
`Strategy` ABC, `Signal` dataclass, backtest runner). This is intentional —
the two domains have different semantics (overnight risk, decision cadence,
cost-as-%-of-move) and forcing them through one abstraction would obscure
the differences. The user has been explicit about this and considers it a
hard rule.

---

## ADR-003 — 2026-05: DuckDB as primary store

**Context.** Need analytical store for market data + transactional store
for signals/trades. Options: SQLite, Postgres+TimescaleDB, DuckDB, Parquet.

**Decision.** DuckDB single file for everything in phase 1.

**Consequences.** Fast analytical queries, single-file backup, no server.
Less ideal for high-write concurrency (irrelevant for personal use).
Migration path to Postgres+TimescaleDB exists if needed (it won't be).

---

## ADR-002 — 2026-05: Upstox Analytics Token (read-only) for phase 1

**Context.** Upstox supports OAuth (full access) and Analytics Token
(read-only, 1-year, no redirect).

**Decision.** Analytics Token only for phase 1.

**Consequences.** No risk of accidental real-money orders. Auth is trivial
(static bearer token). Enforces phase-1 discipline. Will need OAuth later
for sandbox or live orders.

---

## ADR-001 — 2026-05: Python + DuckDB stack, local-only

**Context.** Choosing language and infrastructure for a personal algo
trading project.

**Decision.** Python 3.11+, DuckDB, local Windows machine. No cloud, no
containers, no microservices.

**Consequences.** Fast iteration. Limited by laptop uptime during market
hours. Migrating to VPS is a one-time future cost when warranted.
