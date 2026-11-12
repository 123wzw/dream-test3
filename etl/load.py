"""写入与聚合。"""

import os
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def db_path() -> str:
    return os.environ.get("METRICS_DB", str(BASE_DIR / "warehouse.db"))


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    schema = (BASE_DIR / "sql" / "schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema)
    conn.commit()


def load_ods(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """把新事件写入 ODS，返回新增条数。

    同一 event_id 只保留一条（幂等）；不按水位过滤，
    迟到事件只要 event_id 未出现过就会补入。
    """
    existing = {r[0] for r in conn.execute("SELECT event_id FROM ods_events")}
    fresh = []
    seen = set()
    for r in rows:
        event_id = r["event_id"]
        if event_id in existing or event_id in seen:
            continue
        seen.add(event_id)
        fresh.append(r)
    for r in fresh:
        conn.execute(
            "INSERT INTO ods_events"
            " (event_id, user_id, email, event_type, amount_cents, ts_utc, dt)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (r["event_id"], r["user_id"], r["email"], r["event_type"],
             r["amount_cents"], r["ts_utc"], r["dt"]),
        )
    conn.commit()
    return len(fresh)


def rebuild_dwd(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM dwd_events")
    conn.execute(
        "INSERT INTO dwd_events"
        " (event_id, user_id, email, event_type, amount_cents, ts_utc, dt)"
        " SELECT event_id, user_id, email, event_type, amount_cents, ts_utc, dt"
        " FROM ods_events"
        " WHERE rowid IN (SELECT MIN(rowid) FROM ods_events GROUP BY event_id)"
    )
    conn.commit()


def rebuild_dws(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM dws_daily")
    rows = conn.execute(
        """
        SELECT dt,
               COUNT(DISTINCT user_id) AS dau,
               SUM(CASE WHEN event_type = 'order_paid' THEN 1 ELSE 0 END) AS orders,
               SUM(CASE WHEN event_type = 'order_paid' THEN amount_cents ELSE 0 END) AS gmv_cents
        FROM dwd_events
        GROUP BY dt
        """
    ).fetchall()
    for row in rows:
        conn.execute(
            "INSERT INTO dws_daily (dt, dau, orders, gmv_cents) VALUES (?, ?, ?, ?)",
            (row["dt"], row["dau"], row["orders"], row["gmv_cents"]),
        )
    conn.commit()
