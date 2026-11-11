"""读取上游 CSV。"""

import csv
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def events_csv_path() -> Path:
    return Path(os.environ.get("METRICS_EVENTS", str(BASE_DIR / "data" / "events.csv")))


def read_events() -> list[dict]:
    path = events_csv_path()
    with path.open(encoding="utf-8", newline="") as fh:
        return [dict(row) for row in csv.DictReader(fh)]
