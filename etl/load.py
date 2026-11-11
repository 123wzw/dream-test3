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


def current_watermark(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT MAX(ts_utc) AS wm FROM ods_events").fetchone()
    return row["wm"] if row and row["wm"] else ""


def load_ods(conn: sqlite3.Connection, rows: list[dict], watermark: str) -> int:
    """把水位之后的事件写入 ODS，返回新增条数。"""
    fresh = [r for r in rows if r["ts_utc"] > watermark]
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
        " SELECT event_id, user_id, email, event_type, amount_cents, ts_utc, dt FROM ods_events"
    )
    conn.commit()


def rebuild_dws(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM dws_daily")
    rows = conn.execute(
        """
        SELECT dt,
               COUNT(DISTINCT email) AS dau,
               SUM(CASE WHEN event_type = 'order_paid' THEN 1 ELSE 0 END) AS orders,
               SUM(CASE WHEN event_type = 'order_paid' THEN amount_cents / 100.0 ELSE 0 END) AS gmv
        FROM dwd_events
        GROUP BY dt
        """
    ).fetchall()
    for row in rows:
        conn.execute(
            "INSERT INTO dws_daily (dt, dau, orders, gmv_cents) VALUES (?, ?, ?, ?)",
            (row["dt"], row["dau"], row["orders"], int(row["gmv"])),
        )
    conn.commit()
