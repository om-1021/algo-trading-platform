"""Trading universe definitions.

NIFTY_50 list below is a recent snapshot — index composition changes
~twice a year. Verify against the latest from NSE before any go-live:
  https://www.nseindia.com/market-data/live-equity-market

You can also override the universe at runtime by passing a custom list to
the backfill / strategy runners.
"""

# Note: Tata Motors demerged in Oct 2024 into TMCV (commercial vehicles, the
# renamed parent) and TMPV (passenger vehicles, the spinoff). The original
# TATAMOTORS ticker is no longer listed. Both successors are included here;
# verify current NIFTY 50 membership on NSE before relying on this for live
# strategies.
NIFTY_50: tuple[str, ...] = (
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL",
    "CIPLA", "COALINDIA", "DRREDDY", "EICHERMOT", "ETERNAL",
    "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO",
    "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDUSINDBK", "INFY",
    "ITC", "JIOFIN", "JSWSTEEL", "KOTAKBANK", "LT",
    "M&M", "MARUTI", "NESTLEIND", "NTPC", "ONGC",
    "POWERGRID", "RELIANCE", "SBILIFE", "SBIN", "SHRIRAMFIN",
    "SUNPHARMA", "TATACONSUM", "TMCV", "TMPV", "TATASTEEL", "TCS",
    "TECHM", "TITAN", "TRENT", "ULTRACEMCO", "WIPRO",
)
