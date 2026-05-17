-- ============================================================================
-- ALGO TRADING PLATFORM — DB SCHEMA
-- ============================================================================
-- Conventions:
--   * tables in snake_case
--   * timestamps stored as TIMESTAMPTZ (DuckDB handles offsets)
--   * money / prices stored as DOUBLE (sufficient for INR retail volumes)
--   * NO foreign keys between swing_* and intraday_* tables — lanes are
--     independent and must stay that way.
-- ============================================================================


-- ---------------- SHARED: instruments ---------------------------------------

CREATE TABLE IF NOT EXISTS instruments (
    instrument_key   VARCHAR PRIMARY KEY,   -- e.g. "NSE_EQ|INE002A01018"
    exchange         VARCHAR NOT NULL,      -- "NSE", "BSE"
    segment          VARCHAR NOT NULL,      -- "NSE_EQ", "NSE_FO", ...
    tradingsymbol    VARCHAR NOT NULL,      -- "RELIANCE"
    name             VARCHAR,
    instrument_type  VARCHAR,               -- "EQ", "FUT", "CE", "PE"
    lot_size         INTEGER,
    tick_size        DOUBLE,
    updated_at       TIMESTAMPTZ DEFAULT current_timestamp
);

CREATE INDEX IF NOT EXISTS idx_instruments_symbol ON instruments(tradingsymbol);


-- ---------------- SHARED: daily bars ----------------------------------------

CREATE TABLE IF NOT EXISTS market_bars_daily (
    instrument_key   VARCHAR NOT NULL,
    bar_date         DATE    NOT NULL,
    open             DOUBLE  NOT NULL,
    high             DOUBLE  NOT NULL,
    low              DOUBLE  NOT NULL,
    close            DOUBLE  NOT NULL,
    volume           BIGINT  NOT NULL,
    open_interest    BIGINT  NOT NULL DEFAULT 0,
    PRIMARY KEY (instrument_key, bar_date)
);


-- ---------------- SHARED: intraday minute bars ------------------------------

CREATE TABLE IF NOT EXISTS market_bars_1m (
    instrument_key   VARCHAR     NOT NULL,
    bar_ts           TIMESTAMPTZ NOT NULL,
    open             DOUBLE      NOT NULL,
    high             DOUBLE      NOT NULL,
    low              DOUBLE      NOT NULL,
    close            DOUBLE      NOT NULL,
    volume           BIGINT      NOT NULL,
    open_interest    BIGINT      NOT NULL DEFAULT 0,
    PRIMARY KEY (instrument_key, bar_ts)
);


-- ============================================================================
-- SWING LANE  (daily bars, hold overnight, end-of-day decisions)
-- ============================================================================

CREATE TABLE IF NOT EXISTS swing_strategy_runs (
    run_id           VARCHAR PRIMARY KEY,    -- uuid
    strategy_name    VARCHAR NOT NULL,
    strategy_version VARCHAR NOT NULL,
    params_json      VARCHAR NOT NULL,       -- frozen params for this run
    started_at       TIMESTAMPTZ DEFAULT current_timestamp,
    status           VARCHAR NOT NULL        -- "active" | "paused" | "retired"
);

CREATE TABLE IF NOT EXISTS swing_signals (
    signal_id        VARCHAR PRIMARY KEY,    -- uuid
    run_id           VARCHAR NOT NULL,       -- → swing_strategy_runs.run_id
    instrument_key   VARCHAR NOT NULL,
    signal_ts        TIMESTAMPTZ NOT NULL,
    direction        VARCHAR NOT NULL,       -- "LONG" | "SHORT" | "EXIT"
    entry_price      DOUBLE,
    stop_loss        DOUBLE,
    target           DOUBLE,
    reasoning_json   VARCHAR,                -- indicator values, conditions met
    taken            BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS swing_trades (
    trade_id         VARCHAR PRIMARY KEY,    -- uuid
    entry_signal_id  VARCHAR NOT NULL,       -- → swing_signals
    exit_signal_id   VARCHAR,                -- nullable while open
    run_id           VARCHAR NOT NULL,
    instrument_key   VARCHAR NOT NULL,
    direction        VARCHAR NOT NULL,
    qty              INTEGER NOT NULL,
    entry_ts         TIMESTAMPTZ NOT NULL,
    entry_price      DOUBLE NOT NULL,
    exit_ts          TIMESTAMPTZ,
    exit_price       DOUBLE,
    exit_reason      VARCHAR,                -- "target" | "stop" | "signal" | "manual"
    gross_pnl        DOUBLE,
    cost_estimate    DOUBLE,
    net_pnl          DOUBLE,
    status           VARCHAR NOT NULL        -- "open" | "closed"
);


-- ============================================================================
-- INTRADAY LANE  (minute bars, square off by EOD, no overnight risk)
-- ============================================================================

CREATE TABLE IF NOT EXISTS intraday_strategy_runs (
    run_id           VARCHAR PRIMARY KEY,
    strategy_name    VARCHAR NOT NULL,
    strategy_version VARCHAR NOT NULL,
    params_json      VARCHAR NOT NULL,
    started_at       TIMESTAMPTZ DEFAULT current_timestamp,
    status           VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS intraday_signals (
    signal_id        VARCHAR PRIMARY KEY,
    run_id           VARCHAR NOT NULL,
    instrument_key   VARCHAR NOT NULL,
    signal_ts        TIMESTAMPTZ NOT NULL,
    direction        VARCHAR NOT NULL,
    entry_price      DOUBLE,
    stop_loss        DOUBLE,
    target           DOUBLE,
    reasoning_json   VARCHAR,
    taken            BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS intraday_trades (
    trade_id         VARCHAR PRIMARY KEY,
    entry_signal_id  VARCHAR NOT NULL,
    exit_signal_id   VARCHAR,
    run_id           VARCHAR NOT NULL,
    instrument_key   VARCHAR NOT NULL,
    direction        VARCHAR NOT NULL,
    qty              INTEGER NOT NULL,
    entry_ts         TIMESTAMPTZ NOT NULL,
    entry_price      DOUBLE NOT NULL,
    exit_ts          TIMESTAMPTZ,
    exit_price       DOUBLE,
    exit_reason      VARCHAR,                -- includes "eod_squareoff"
    gross_pnl        DOUBLE,
    cost_estimate    DOUBLE,
    net_pnl          DOUBLE,
    status           VARCHAR NOT NULL
);


-- ============================================================================
-- AGENT LAYER  (cross-lane, but carries 'lane' so we never mix in queries)
-- ============================================================================

CREATE TABLE IF NOT EXISTS agent_decisions (
    decision_id      VARCHAR PRIMARY KEY,
    lane             VARCHAR NOT NULL,       -- "swing" | "intraday"
    agent_role       VARCHAR NOT NULL,       -- "generator" | "critic" | "regime" | "postmortem"
    decision_ts      TIMESTAMPTZ DEFAULT current_timestamp,
    linked_signal_id VARCHAR,                -- optional fk into swing_signals OR intraday_signals
    prompt           VARCHAR NOT NULL,
    response         VARCHAR NOT NULL,
    model            VARCHAR,
    tokens_in        INTEGER,
    tokens_out       INTEGER
);


-- ============================================================================
-- DATA HEALTH  (silent failures are the worst — surface them)
-- ============================================================================

CREATE TABLE IF NOT EXISTS data_health_events (
    event_id         VARCHAR PRIMARY KEY,
    event_ts         TIMESTAMPTZ DEFAULT current_timestamp,
    severity         VARCHAR NOT NULL,       -- "info" | "warn" | "error"
    component        VARCHAR NOT NULL,       -- "ws_feed" | "backfill" | "scheduler"
    message          VARCHAR NOT NULL,
    context_json     VARCHAR
);


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
