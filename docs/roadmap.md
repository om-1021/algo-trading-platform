# Roadmap

Living document — reorder freely. The numbered items are not strictly
sequential, but the user generally works top-to-bottom.

For decisions about scope (what we're *not* building), see
`docs/architecture.md` final section and `CLAUDE.md` section 9.

---

## Immediate (next 1–2 sessions)

1. **User runs phase-1 scripts on real data**
   - `python scripts/init_db.py`
   - `python scripts/healthcheck.py` — verify analytics token
   - `python scripts/backfill_daily.py` — 3 years of Nifty 50 dailies
   - `python scripts/backtest_swing.py` — first real EMA crossover result

2. **Walk-forward validation harness**  *(most important next addition)*
   - Splits history into rolling train/test windows
   - Runs strategy on each, reports out-of-sample metrics only
   - New table `swing_walkforward_runs` or extend `swing_strategy_runs`
   - Without this, every backtest result is unreliable

3. **Streamlit dashboard (swing page only)**
   - Today's signals, open trades, per-strategy cumulative P&L
   - Reasoning drawer (click any trade → see full JSON)
   - Equity curve per run
   - **Strictly swing-only** — no intraday widgets on this page

---

## Near-term (next 5–10 sessions)

4. **Second swing strategy: RSI mean-reversion**
   - Validates that the framework supports a different strategy archetype
   - Forces the backtest runner to handle more diverse signal patterns

5. **Third swing strategy: Bollinger band squeeze / breakout**
   - Volatility-based, different again

6. **Live paper trading mode for swing**
   - EOD scheduler that runs strategies on the latest bars
   - Generates today's signals into `swing_signals`
   - Updates open positions
   - Different from backtest mode (which sweeps history)

7. **Intraday lane foundation**
   - WebSocket consumer for live 1-min bars → `market_bars_1m`
   - Gap detection and backfill via Intraday Candle Data V3
   - Logs disconnects to `data_health_events`

8. **First intraday strategy: Opening Range Breakout**
   - 15-min opening range, breakout in either direction
   - Square off by EOD (mandatory for the intraday lane)
   - Intraday-specific paper engine with slippage assumptions

9. **Streamlit dashboard: intraday page**
   - Separate page, separate widgets, no shared P&L view with swing

---

## Medium-term

10. **Cost model precision via Upstox brokerage endpoint**
    - Replace the 0.075% per leg approximation
    - Cache results per (notional, segment, direction)

11. **Regime classification (first agent)**
    - LLM agent reads daily market data + VIX + macro news
    - Tags current regime: trending / chopping / volatile / quiet
    - Strategies subscribe to regimes and activate/deactivate themselves
    - Logged in `agent_decisions`

12. **Strategy critic (second agent)**
    - Reviews proposed strategies for known anti-patterns
    - Look-ahead bias, survivorship bias, overfitting risk
    - Runs before a strategy is allowed to promote to walk-forward stage

13. **Strategy generator (third agent)**
    - Synthesizes papers, news, forum posts into formal strategy specs
    - Output goes into Stage 1 (hypothesis) of the promotion pipeline
    - Always human-reviewed before promotion

---

## Longer-term

14. **F&O / options strategies**
    - Different architecture: multi-leg orders, Greeks, IV surface
    - Probably its own sub-lane within intraday or its own third lane
    - Significant new tables and entities

15. **Real money trading (Stage 5 promotion)**
    - Requires full OAuth + order placement APIs
    - Risk controls: per-trade max, per-day max, kill switch
    - Live-vs-paper performance monitoring
    - Months away, do not start until phase 1–2 strategies have survived
      meaningful paper trading

16. **VPS migration**
    - When laptop uptime becomes the bottleneck
    - Probably a small Hetzner / DigitalOcean instance
    - Brings in: deployment scripts, secrets management, monitoring

17. **Multi-broker abstraction**
    - Only if Upstox becomes the bottleneck
    - Abstract over the Upstox client behind a `BrokerInterface` protocol
    - Add a second implementation (e.g. Dhan, Zerodha)

---

## Explicitly out of scope (do not build)

- HFT, latency arbitrage
- Copy trading / signal selling
- A web product for other users
- Mobile app
- A "magic" single strategy that prints money
