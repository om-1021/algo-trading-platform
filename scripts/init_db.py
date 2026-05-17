"""Create the DuckDB schema. Idempotent — safe to re-run."""
import sys
from pathlib import Path

# Add project root to path so `import config` works.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger

from src.storage import init_schema


def main() -> None:
    init_schema()
    logger.success("Database ready.")


if __name__ == "__main__":
    main()
