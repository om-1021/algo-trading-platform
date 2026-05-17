# Algo Trading Platform

Personal AI-augmented algo trading platform for NSE/BSE.
Phase 1: signal-only paper trading with full decision audit trail.

## Architectural principle: strict lane separation

Swing and intraday are kept fully separate in code, storage, and UI.
They share only raw market data — never strategies, signals, trades, or P&L.

```
src/
  upstox/      Read-only API client (analytics token)
  storage/     DuckDB schema and connection
  data/        Universe definitions, instrument master, backfills
  swing/       Swing-only strategies, signals, paper engine  (lane A)
  intraday/    Intraday-only strategies, signals, paper engine (lane B)
  agents/      Agent layer (strategy ideation, critique, regime)
scripts/       Entry-point scripts: init_db, backfill, healthcheck
```

## Setup

1. Python 3.11+ recommended.
2. Create a virtualenv:
   ```
   python -m venv .venv
   source .venv/bin/activate    # macOS/Linux
   .venv\Scripts\activate       # Windows
   ```
3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
4. Copy `.env.example` to `.env` and paste your Upstox analytics token:
   ```
   cp .env.example .env
   # edit .env: UPSTOX_ANALYTICS_TOKEN=<your token>
   ```
5. Initialize the database:
   ```
   python scripts/init_db.py
   ```
6. Verify Upstox connectivity:
   ```
   python scripts/healthcheck.py
   ```
7. Backfill daily bars for Nifty 50 (last 3 years):
   ```
   python scripts/backfill_daily.py
   ```

## What's here in the starter kit

- Upstox client (historical candles, instruments lookup)
- DuckDB schema with lane-separated tables
- Nifty 50 universe definition
- Daily-bar backfill script (the swing-lane foundation)

## What's next (not yet built)

- Live WebSocket consumer (intraday-lane foundation)
- First swing strategies (EMA crossover, RSI mean reversion)
- First intraday strategy (Opening Range Breakout)
- Paper-trade engine (separate one per lane)
- Streamlit dashboard (separate pages per lane)
- Agent layer
