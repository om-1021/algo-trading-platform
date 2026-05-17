# Code Conventions

Quick reference for an agent making changes. Keep it short on purpose.

---

## Python style

- **Python 3.11+** features OK: `match` statements, `Self`, `tomllib`, etc.
- Type hints everywhere. `from __future__ import annotations` at top of modules.
- Dataclasses for value objects. Pydantic only if validating untrusted input.
- f-strings for formatting. No `%`-style.
- Loguru for logging (`from loguru import logger`), not stdlib logging.
- Absolute imports for project code: `from src.swing.base import SwingSignal`.

## Naming

| Kind | Style | Example |
|---|---|---|
| modules / packages | `snake_case` | `ema_crossover.py` |
| classes | `PascalCase` | `EmaCrossover` |
| functions / variables | `snake_case` | `generate_signals`, `run_id` |
| constants | `SCREAMING_SNAKE_CASE` | `DEFAULT_COST_BPS_PER_LEG` |
| private helpers | `_leading_underscore` | `_persist_signals` |
| tables | `snake_case`, lane-prefixed | `swing_signals` |
| columns | `snake_case` | `entry_price` |

## File length

Soft cap of ~200 lines per Python file. Split when it exceeds. Lots of small
focused modules > a few god modules.

## SQL

- Schema in `src/storage/schema.sql` is the source of truth
- All queries use parameterized placeholders (`?` for DuckDB) — never string
  concatenation
- Lane prefix on all table names (`swing_*` or `intraday_*`) unless genuinely
  shared
- Never JOIN swing tables with intraday tables

## Error handling

- Don't swallow exceptions silently. Either re-raise or log via `loguru` AND
  record to `data_health_events` if it's a runtime/data issue.
- Don't introduce broad `except Exception:` blocks unless you also re-raise
  or log a useful message.
- Failures in one symbol's backfill should not crash the whole job — skip
  the symbol, log, continue. This pattern is shown in `scripts/backfill_daily.py`.

## Testing

We don't have a formal test suite yet. Smoke tests live in `scripts/smoke_*.py`
and run against synthetic data. When real strategies arrive, we'll add a
`tests/` directory with pytest. Until then:

- After any change to swing code, run `python scripts/smoke_test_swing.py` —
  must pass with the same shape of output before committing
- After any schema change, re-run `python scripts/init_db.py` and confirm no
  errors
- After any Upstox client change, run `python scripts/healthcheck.py`

## Comments

- Prefer self-documenting code over comments.
- Use docstrings (Google-style or plain) on all public functions.
- Comments explain *why*, not *what*. The code says *what*.
- Module-level docstrings at the top of every file explain the module's role.

## Imports

Order: stdlib → third-party → local. Blank line between groups.

```python
from __future__ import annotations

import json
import uuid
from datetime import datetime

import pandas as pd
from loguru import logger

from src.storage import get_conn
from src.swing.base import SwingSignal
```

## Git

- Commit messages: imperative mood, lowercase, no period. `add ema crossover
  strategy` not `Added EMA crossover strategy.`.
- `.env` is never committed.
- DuckDB files (`*.duckdb`) are never committed.
- Synthetic test artifacts under `data/` are git-ignored.
- One logical change per commit. Keep diffs reviewable.
