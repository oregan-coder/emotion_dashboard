"""Import full-market daily-K CSV aggregates into the narrow breadth fact table."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from collection.market_breadth_store import import_daily_k_csv


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--db", type=Path,
                        default=ROOT / "data" / ".migration_shadow" / "market_store_5535.next.sqlite3")
    args = parser.parse_args()
    print(json.dumps(import_daily_k_csv(args.db, args.csv_path), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
