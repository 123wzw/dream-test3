"""清洗与字段规范化。"""

from datetime import datetime, timezone


def parse_ts(ts_utc: str) -> datetime:
    return datetime.fromisoformat(ts_utc.replace("Z", "+00:00"))


def to_partition(ts_utc: str) -> str:
    """把事件时间换算成分区日期（一律取 UTC 日期）。"""
    return parse_ts(ts_utc).astimezone(timezone.utc).date().isoformat()


def normalize(row: dict) -> dict:
    amount_raw = (row.get("amount_cents") or "").strip() or "0"
    return {
        "event_id": row["event_id"].strip(),
        "user_id": row["user_id"].strip().lower(),
        "email": (row.get("email") or "").strip().lower() or None,
        "event_type": row["event_type"].strip(),
        "amount_cents": int(amount_raw),
        "ts_utc": parse_ts(row["ts_utc"]).astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
