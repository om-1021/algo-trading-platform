"""Backfill daily OHLCV bars for the Nifty 50 universe.

Strategy: one API call per symbol covering the full range (Upstox V3 daily
candles allow up to a decade per request, so 3 years is one call each).

Idempotent: uses INSERT OR REPLACE so re-running is safe and updates the
latest bar if it changes (e.g. corporate action adjustments).
"""
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger

from config import settings
from src.data.universe import NIFTY_50
from src.storage import get_conn, init_schema
from src.upstox import UpstoxClient
from src.upstox.instruments import lookup_equity_keys

LOOKBACK_YEARS = 3


def _persist_instruments(symbol_to_key: dict[str, str]) -> None:
    """Upsert instruments table with the symbols we care about."""
    rows = [
        (key, "NSE", "NSE_EQ", sym, sym, "EQ", None, None)
        for sym, key in symbol_to_key.items()
    ]
    with get_conn() as conn:
        conn.executemany(
            """
            INSERT INTO instruments
              (instrument_key, exchange, segment, tradingsymbol, name,
               instrument_type, lot_size, tick_size)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (instrument_key) DO UPDATE SET
              tradingsymbol = excluded.tradingsymbol,
              updated_at = now()
            """,
            rows,
        )
    logger.info("Persisted {} instruments", len(rows))


def _persist_daily_bars(instrument_key: str, candles: list) -> int:
    """Insert daily bars; returns count inserted."""
    if not candles:
        return 0
    rows = []
    for c in candles:
        # Parse "2025-01-01T00:00:00+05:30" → date
        bar_date = date.fromisoformat(c.timestamp[:10])
        rows.append((
            instrument_key, bar_date,
            c.open, c.high, c.low, c.close, c.volume, c.open_interest,
        ))
    with get_conn() as conn:
        conn.executemany(
            """
            INSERT INTO market_bars_daily
              (instrument_key, bar_date, open, high, low, close, volume, open_interest)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (instrument_key, bar_date) DO UPDATE SET
              open = excluded.open,
              high = excluded.high,
              low = excluded.low,
              close = excluded.close,
              volume = excluded.volume,
              open_interest = excluded.open_interest
            """,
            rows,
        )
    return len(rows)


def _log_health(severity: str, component: str, message: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO data_health_events (event_id, severity, component, message) "
            "VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), severity, component, message),
        )


def main(symbols: tuple[str, ...] = NIFTY_50) -> None:
    init_schema()

    # 1. Resolve instrument_keys for the universe.
    keymap = lookup_equity_keys(list(symbols))
    if not keymap:
        logger.error("No instrument keys resolved. Aborting.")
        return
    _persist_instruments(keymap)

    # 2. Fetch + persist daily candles for each.
    client = UpstoxClient(settings.upstox_analytics_token)
    today = date.today()
    from_date = today - timedelta(days=LOOKBACK_YEARS * 365)

    total = 0
    failures: list[str] = []
    for sym, key in keymap.items():
        try:
            candles = client.historical_candles(
                instrument_key=key,
                unit="days",
                interval=1,
                to_date=today,
                from_date=from_date,
            )
            n = _persist_daily_bars(key, candles)
            total += n
            logger.info("  {:<14} → {:>4} bars", sym, n)
        except Exception as e:
            failures.append(sym)
            logger.error("  {:<14} FAILED: {}", sym, e)
            _log_health("error", "backfill", f"{sym}: {e}")

    logger.success("Backfill complete. {} bars across {} symbols.", total, len(keymap) - len(failures))
    if failures:
        logger.warning("Failed symbols: {}", failures)


if __name__ == "__main__":
    main()
