"""Quick sanity check: can we talk to Upstox with the analytics token?

Run this after pasting your token into .env. It hits two read-only endpoints
and prints the result. If both succeed, you're ready to backfill data.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger

from config import settings
from src.upstox import UpstoxClient
from src.upstox.instruments import lookup_equity_keys


def main() -> None:
    client = UpstoxClient(settings.upstox_analytics_token)

    # 1. Market status — cheap, no data dependencies.
    try:
        status = client.market_status("NSE")
        logger.success("Market status OK: {}", status.get("data"))
    except Exception as e:
        logger.error("Market status failed: {}", e)
        raise

    # 2. Fetch a few daily candles for RELIANCE.
    keys = lookup_equity_keys(["RELIANCE"])
    if "RELIANCE" not in keys:
        logger.error("Could not find RELIANCE instrument_key; check instrument master.")
        return
    rel_key = keys["RELIANCE"]
    logger.info("RELIANCE instrument_key = {}", rel_key)

    today = date.today()
    candles = client.historical_candles(
        instrument_key=rel_key,
        unit="days",
        interval=1,
        to_date=today,
        from_date=today - timedelta(days=14),
    )
    logger.success("Got {} daily candles for RELIANCE", len(candles))
    for c in candles[-3:]:
        logger.info("  {}  O={} H={} L={} C={} V={}",
                    c.timestamp, c.open, c.high, c.low, c.close, c.volume)


if __name__ == "__main__":
    main()
