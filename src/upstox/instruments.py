"""Instrument master: downloads Upstox's NSE instrument list and provides
a tradingsymbol → instrument_key lookup.

The master is published as a gzipped CSV at:
  https://assets.upstox.com/market-quote/instruments/exchange/NSE.csv.gz

We cache it locally for 24h to avoid hammering their CDN.
"""
from __future__ import annotations

import gzip
import io
import time
from pathlib import Path

import pandas as pd
import requests
from loguru import logger

INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.csv.gz"
CACHE_PATH = Path("./data/instruments_nse.parquet")
CACHE_TTL_SECONDS = 24 * 3600


def _download_master() -> pd.DataFrame:
    logger.info("Downloading Upstox NSE instrument master...")
    resp = requests.get(INSTRUMENTS_URL, timeout=60)
    resp.raise_for_status()
    with gzip.open(io.BytesIO(resp.content), "rt") as f:
        df = pd.read_csv(f)
    logger.info("Downloaded {} instruments", len(df))
    return df


def load_instrument_master(force_refresh: bool = False) -> pd.DataFrame:
    """Returns the NSE instrument master as a DataFrame.

    Columns vary slightly by Upstox version but typically include:
      instrument_key, exchange_token, tradingsymbol, name, last_price,
      expiry, strike, tick_size, lot_size, instrument_type, segment, exchange
    """
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fresh = (
        CACHE_PATH.exists()
        and (time.time() - CACHE_PATH.stat().st_mtime) < CACHE_TTL_SECONDS
        and not force_refresh
    )
    if fresh:
        logger.debug("Loading instrument master from cache: {}", CACHE_PATH)
        return pd.read_parquet(CACHE_PATH)

    df = _download_master()
    df.to_parquet(CACHE_PATH, index=False)
    return df


def lookup_equity_keys(symbols: list[str]) -> dict[str, str]:
    """Map cash-equity trading symbols (e.g. 'RELIANCE') to instrument_key
    (e.g. 'NSE_EQ|INE002A01018').

    Returns a dict; missing symbols are omitted and logged.
    """
    df = load_instrument_master()
    # Filter to NSE cash equity. Upstox uses segment 'NSE_EQ' for cash.
    if "segment" in df.columns:
        eq = df[df["segment"] == "NSE_EQ"]
    else:
        eq = df
    # 'tradingsymbol' is the human ticker like 'RELIANCE'
    ts_col = "tradingsymbol" if "tradingsymbol" in eq.columns else "trading_symbol"
    key_col = "instrument_key"
    mapping = dict(zip(eq[ts_col].astype(str), eq[key_col].astype(str)))
    out: dict[str, str] = {}
    missing: list[str] = []
    for sym in symbols:
        if sym in mapping:
            out[sym] = mapping[sym]
        else:
            missing.append(sym)
    if missing:
        logger.warning("Instrument keys not found for: {}", missing)
    return out
