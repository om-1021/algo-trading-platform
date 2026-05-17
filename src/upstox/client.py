"""Upstox REST client using the Analytics Token (read-only).

Endpoints covered:
- Historical Candle Data V3
- Intraday Candle Data V3
- Market Status
- LTP / OHLC quotes

All other write/order endpoints are intentionally NOT implemented because
the analytics token is read-only. This is a feature, not a limitation —
it enforces phase 1's signal-only paper trading discipline.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable
from urllib.parse import quote

import requests
from loguru import logger


@dataclass
class Candle:
    """One OHLCV candle. Matches Upstox V3 response tuple order."""
    timestamp: str          # ISO with offset, e.g. "2025-01-01T00:00:00+05:30"
    open: float
    high: float
    low: float
    close: float
    volume: int
    open_interest: int

    @classmethod
    def from_tuple(cls, t: list) -> "Candle":
        return cls(
            timestamp=t[0],
            open=float(t[1]),
            high=float(t[2]),
            low=float(t[3]),
            close=float(t[4]),
            volume=int(t[5]),
            open_interest=int(t[6]) if len(t) > 6 else 0,
        )


class UpstoxClient:
    """Thin wrapper around Upstox V3 read-only endpoints."""

    BASE_URL = "https://api.upstox.com"
    DEFAULT_TIMEOUT = 15  # seconds
    # Conservative pacing to stay well under Upstox rate limits.
    # See https://upstox.com/developer/api-documentation/rate-limiting
    MIN_INTERVAL_SECONDS = 0.25

    def __init__(self, analytics_token: str) -> None:
        self._token = analytics_token
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {analytics_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        self._last_call_ts = 0.0

    # ---------- internal ----------

    def _throttle(self) -> None:
        delta = time.monotonic() - self._last_call_ts
        if delta < self.MIN_INTERVAL_SECONDS:
            time.sleep(self.MIN_INTERVAL_SECONDS - delta)
        self._last_call_ts = time.monotonic()

    def _get(self, path: str, params: dict | None = None) -> dict[str, Any]:
        self._throttle()
        url = f"{self.BASE_URL}{path}"
        logger.debug("GET {}", url)
        resp = self._session.get(url, params=params, timeout=self.DEFAULT_TIMEOUT)
        if resp.status_code >= 400:
            logger.error("Upstox {} → {} {}", url, resp.status_code, resp.text[:300])
            resp.raise_for_status()
        return resp.json()

    # ---------- historical ----------

    def historical_candles(
        self,
        instrument_key: str,
        unit: str,
        interval: int | str,
        to_date: date,
        from_date: date | None = None,
    ) -> list[Candle]:
        """Fetch historical OHLC candles.

        Args:
            instrument_key: e.g. "NSE_EQ|INE002A01018"
            unit: "minutes" | "hours" | "days" | "weeks" | "months"
            interval: numeric interval valid for the chosen unit
            to_date: inclusive end date
            from_date: optional start date

        Returns:
            List of Candle in chronological order (Upstox returns newest-first;
            we reverse to make downstream code simpler).
        """
        encoded_key = quote(instrument_key, safe="")
        path = f"/v3/historical-candle/{encoded_key}/{unit}/{interval}/{to_date.isoformat()}"
        if from_date:
            path += f"/{from_date.isoformat()}"
        payload = self._get(path)
        candles = payload.get("data", {}).get("candles", [])
        parsed = [Candle.from_tuple(c) for c in candles]
        # Upstox returns most-recent-first; flip for ascending order.
        parsed.reverse()
        return parsed

    # ---------- market info ----------

    def market_status(self, exchange: str = "NSE") -> dict[str, Any]:
        """Exchange status (open/closed/holiday)."""
        return self._get(f"/v2/market/status/{exchange}")

    def ltp(self, instrument_keys: Iterable[str]) -> dict[str, Any]:
        """Last traded price for one or more instrument keys (V3)."""
        keys = ",".join(instrument_keys)
        return self._get("/v3/market-quote/ltp", params={"instrument_key": keys})
