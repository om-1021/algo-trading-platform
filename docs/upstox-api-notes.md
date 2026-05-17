# Upstox API Notes

Operational knowledge about the Upstox V3 API as used by this project.
Updated as we discover quirks.

Official docs: https://upstox.com/developer/api-documentation/

---

## Authentication: Analytics Token

We use the **Analytics Token**, not the full OAuth flow.

- Generated at https://account.upstox.com/developer/apps → Analytics tab
- Valid for **1 year** from generation
- **One token per account at a time** — regenerating revokes the old one
- Read-only: cannot place orders, cannot read positions/holdings/funds
- Sent as `Authorization: Bearer <token>` header

Token lives in `.env` as `UPSTOX_ANALYTICS_TOKEN`. The user re-generates it
yearly (calendar reminder recommended).

### Supported endpoints with Analytics Token

| API | Used in our code? |
|---|---|
| Full market quotes | not yet |
| OHLC quotes V3 | not yet |
| LTP quotes V3 | yes (`UpstoxClient.ltp`) |
| Historical candle data V3 | yes (`UpstoxClient.historical_candles`) |
| Intraday candle data V3 | planned (intraday lane) |
| Market Data Feed V3 (WebSocket) | planned (intraday live data) |
| Market Data Feed Authorize V3 | planned (precursor to WebSocket) |
| Brokerage Details | planned (precise cost model) |
| Market Status | yes (`UpstoxClient.market_status`) |
| Put/Call Option chain | not yet (F&O phase) |
| Option contracts | not yet |
| Margin Details | not yet |
| Option Greeks | not yet |
| Instrument Search | not yet |

What we **cannot** do with Analytics Token: place orders, modify orders,
read positions, read holdings, read funds, read user profile, read trade
history. None of this is needed for phase 1.

---

## Historical Candle Data V3

Endpoint:
```
GET https://api.upstox.com/v3/historical-candle/{instrument_key}/{unit}/{interval}/{to_date}/{from_date}
```

`instrument_key` is URL-encoded (pipe `|` becomes `%7C`).
Format: `NSE_EQ|INE002A01018` (segment + ISIN, separated by pipe).

### Limits

| Unit | Interval | History | Max per call |
|---|---|---|---|
| minutes | 1–300 | from Jan 2022 | 1 month (intervals 1–15m); 1 quarter (>15m) |
| hours | 1–5 | from Jan 2022 | 1 quarter |
| days | 1 | from Jan 2000 | 1 decade |
| weeks | 1 | from Jan 2000 | no limit |
| months | 1 | from Jan 2000 | no limit |

So a 3-year daily backfill for Nifty 50 = 50 calls, ~1 minute end to end.
A 1-year 1-minute backfill for Nifty 50 = 50 × 12 = 600 calls. Use the
internal throttle (`MIN_INTERVAL_SECONDS`) to stay under rate limits.

### Response shape

```json
{
  "status": "success",
  "data": {
    "candles": [
      ["2025-01-01T00:00:00+05:30", 53.1, 53.95, 51.6, 52.05, 235519861, 0]
    ]
  }
}
```

Order: `[timestamp, open, high, low, close, volume, open_interest]`.
**Returned newest-first** — our client reverses for chronological order.
Timestamp is ISO with IST offset (`+05:30`).

---

## Instrument Master

Downloadable CSV:
```
https://assets.upstox.com/market-quote/instruments/exchange/NSE.csv.gz
```

Updated daily. Cached locally for 24 hours by `src/upstox/instruments.py`.

Columns (subject to change between Upstox releases):
- `instrument_key` — e.g. `NSE_EQ|INE002A01018`
- `exchange_token`, `tradingsymbol`, `name`
- `last_price`, `expiry`, `strike`
- `tick_size`, `lot_size`
- `instrument_type` — "EQ", "FUT", "CE", "PE"
- `segment` — "NSE_EQ", "NSE_FO", "BSE_EQ", etc.
- `exchange` — "NSE", "BSE"

For cash equity lookup, filter `segment == "NSE_EQ"`.

If Upstox renames columns, `lookup_equity_keys()` in `instruments.py` will
silently fail or misroute — keep this in mind when debugging missing keys.

---

## Rate Limits

Upstox enforces per-second and per-minute limits, plus daily caps. Exact
numbers change; check the rate limits page when in doubt. Current Upstox
documented limits are at:
https://upstox.com/developer/api-documentation/rate-limiting

Our client throttles to one request every 250ms (`MIN_INTERVAL_SECONDS = 0.25`)
which is conservative. Bump down if you see HTTP 429s.

On 429: back off exponentially, log to `data_health_events`, do not crash
the whole backfill — just skip the symbol and retry later.

---

## Market Data Feed V3 (WebSocket) — planned, not yet built

For live tick / 1-min bar data during market hours.

Flow:
1. Call `GET /v3/feed/market-data-feed/authorize` to get a WebSocket URL
2. Connect to that URL with the analytics token
3. Send a subscription frame with `instrument_keys` and `mode`
4. Receive streaming binary frames (Upstox uses Protocol Buffers)

This is the foundation of the intraday lane. To be built. See:
https://upstox.com/developer/api-documentation/websocket

Key things to handle:
- Reconnect on disconnect (will happen)
- Backfill missing minutes on reconnect via Intraday Candle Data V3
- Log every disconnect to `data_health_events`
- Throttle subscription updates

---

## Common API gotchas (to be added as discovered)

- *None yet — populate this as we hit them.*

---

## Endpoints we will care about later

- **Option Chain + Greeks** — for F&O strategies in phase 2+
- **Brokerage Details** — for precise cost model
- **Market Status** — to skip days the exchange is closed (holiday calendar
  built-in via API rather than maintaining our own)

---

## Regulatory context (as of mid-2026)

SEBI's algo trading framework was updated in 2024–25. Brokers must register
algos under certain conditions. For personal, low-frequency, non-broadcast
algo usage, retail users are typically below the registration threshold.
**This is not legal advice** — the user should glance at Upstox's algo
policy page before going live with real money:
https://community.upstox.com/t/important-update-regulatory-changes-for-api-and-algo-trading-are-now-live/14874
