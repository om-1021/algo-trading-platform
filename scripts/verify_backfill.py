"""Quick sanity check after backfill_daily.py — counts rows, shows coverage."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb
from config import settings

con = duckdb.connect(str(settings.db_path), read_only=True)

print("=== instruments table ===")
n_instr = con.sql("SELECT COUNT(*) FROM instruments").fetchone()[0]
print(f"  rows: {n_instr}")

print("\n=== market_bars_daily ===")
n_bars = con.sql("SELECT COUNT(*) FROM market_bars_daily").fetchone()[0]
print(f"  total bars: {n_bars}")

print("\n=== per-symbol coverage (top 5 + bottom 5 by bar count) ===")
df = con.sql(
    """
    SELECT i.tradingsymbol, COUNT(*) AS bars,
           MIN(b.bar_date) AS first_bar, MAX(b.bar_date) AS last_bar
    FROM market_bars_daily b
    JOIN instruments i USING (instrument_key)
    GROUP BY 1
    ORDER BY bars DESC
    """
).fetchdf()
print(df.head(5).to_string(index=False))
print("...")
print(df.tail(5).to_string(index=False))

print("\n=== data_health_events ===")
n_err = con.sql("SELECT COUNT(*) FROM data_health_events").fetchone()[0]
print(f"  events: {n_err}")
if n_err:
    print(con.sql("SELECT event_ts, severity, component, message FROM data_health_events ORDER BY event_ts DESC LIMIT 10").fetchdf().to_string(index=False))
