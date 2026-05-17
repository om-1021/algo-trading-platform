"""Centralized configuration loader.

All env access goes through this module so we never sprinkle os.getenv calls
across the codebase. Import `settings` from here.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
_PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(_PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    upstox_analytics_token: str
    db_path: Path
    log_level: str
    project_root: Path

    @classmethod
    def load(cls) -> "Settings":
        token = os.getenv("UPSTOX_ANALYTICS_TOKEN", "").strip()
        if not token or token == "paste-your-token-here":
            raise RuntimeError(
                "UPSTOX_ANALYTICS_TOKEN missing. Copy .env.example to .env "
                "and paste your token."
            )
        db_path = Path(os.getenv("DB_PATH", "./data/algo.duckdb")).resolve()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return cls(
            upstox_analytics_token=token,
            db_path=db_path,
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            project_root=_PROJECT_ROOT,
        )


settings = Settings.load()
