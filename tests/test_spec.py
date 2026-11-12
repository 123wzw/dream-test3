"""口径回归测试：每条用例对应 docs/SPEC.md 的一条口径。

这些测试在当前实现下必须全部失败，修复后必须全部通过。
"""

import csv

import pytest

from etl import load, transform
from etl.run import run

HEADER = ["event_id", "user_id", "email", "event_type", "amount_cents", "ts_utc"]


def _write_events(tmp_path, rows):
    path = tmp_path / "events.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(HEADER)
        writer.writerows(rows)


@pytest.fixture()
def warehouse(tmp_path, monkeypatch):
    """每个用例使用独立的 CSV 与数据库，互不影响。"""
    monkeypatch.setenv("METRICS_DB", str(tmp_path / "warehouse.db"))
    monkeypatch.setenv("METRICS_EVENTS", str(tmp_path / "events.csv"))
    return tmp_path


def _dws_by_dt(result):
    return {row["dt"]: row for row in result["dws"]}


def test_partition_uses_utc_date(warehouse):
    """SPEC §1：dt 取 ts_utc 的 UTC 日期，不得用本地时区换算。"""
    assert transform.to_partition("2024-03-01T23:30:00Z") == "2024-03-01"
    assert transform.to_partition("2024-03-02T00:10:00Z") == "2024-03-02"


def test_amount_cents_parsed_as_integer(warehouse):
    """SPEC §4：金额一律整数分，禁止浮点参与中间计算（大整数经 float 会丢精度）。"""
    row = {
        "event_id": "e1",
        "user_id": "u1",
        "email": "a@x.com",
        "event_type": "order_paid",
        "amount_cents": "9007199254740993",  # 2^53 + 1，float 无法精确表示
        "ts_utc": "2024-03-01T00:00:00Z",
    }
    item = transform.normalize(row)
    assert isinstance(item["amount_cents"], int)
    assert item["amount_cents"] == 9007199254740993


def test_dau_counts_distinct_user_id(warehouse):
    """SPEC §4：DAU 按 user_id 去重；同一 user_id 绑定多个邮箱只计 1 人。"""
    _write_events(warehouse, [
        ["e1", "u1", "alice@x.com", "page_view", "0", "2024-03-01T10:00:00Z"],
        ["e2", "u1", "alice.work@x.com", "page_view", "0", "2024-03-01T11:00:00Z"],
        ["e3", "u2", "bob@x.com", "page_view", "0", "2024-03-01T12:00:00Z"],
    ])
    dws = _dws_by_dt(run())
    assert dws["2024-03-01"]["dau"] == 2


def test_gmv_is_integer_sum_of_cents(warehouse):
    """SPEC §4：GMV 是 order_paid 的 amount_cents 整数之和，单位分，禁止浮点。"""
    _write_events(warehouse, [
        ["e1", "u1", "a@x.com", "order_paid", "1299", "2024-03-01T10:00:00Z"],
        ["e2", "u2", "b@x.com", "order_paid", "2599", "2024-03-01T11:00:00Z"],
        ["e3", "u3", "c@x.com", "order_paid", "1", "2024-03-01T12:00:00Z"],
        ["e4", "u1", "a@x.com", "page_view", "0", "2024-03-01T13:00:00Z"],
    ])
    dws = _dws_by_dt(run())
    assert dws["2024-03-01"]["orders"] == 3
    assert dws["2024-03-01"]["gmv_cents"] == 3899


def test_duplicate_event_id_loaded_once(warehouse):
    """SPEC §2/§5：同一 event_id 只允许一条有效记录，重复上报不得重复计数。"""
    _write_events(warehouse, [
        ["e1", "u1", "a@x.com", "order_paid", "1299", "2024-03-01T10:00:00Z"],
        ["e1", "u1", "a@x.com", "order_paid", "1299", "2024-03-01T10:00:00Z"],  # 重复上报
        ["e2", "u2", "b@x.com", "order_paid", "100", "2024-03-01T11:00:00Z"],
    ])
    result = run()
    conn = load.connect()
    try:
        ods = conn.execute("SELECT COUNT(*) FROM ods_events WHERE event_id = 'e1'").fetchone()[0]
        dwd = conn.execute("SELECT COUNT(*) FROM dwd_events WHERE event_id = 'e1'").fetchone()[0]
    finally:
        conn.close()
    assert ods == 1
    assert dwd == 1
    dws = _dws_by_dt(result)
    assert dws["2024-03-01"]["orders"] == 2
    assert dws["2024-03-01"]["gmv_cents"] == 1399


def test_late_event_within_24h_backfilled(warehouse):
    """SPEC §3：迟到事件（ts_utc 早于当前水位、落在已加工区间内）必须补入，

    且所属 dt 分区的 DWS 指标同步更新。
    """
    _write_events(warehouse, [
        ["e1", "u1", "a@x.com", "order_paid", "1000", "2024-03-01T10:00:00Z"],
        ["e2", "u2", "b@x.com", "order_paid", "2000", "2024-03-01T20:00:00Z"],
    ])
    first = run()
    dws = _dws_by_dt(first)
    assert dws["2024-03-01"]["orders"] == 2
    assert dws["2024-03-01"]["gmv_cents"] == 3000

    # 迟到事件 e3：ts_utc=15:00 早于水位 20:00，但在 24 小时迟到窗口内
    _write_events(warehouse, [
        ["e1", "u1", "a@x.com", "order_paid", "1000", "2024-03-01T10:00:00Z"],
        ["e2", "u2", "b@x.com", "order_paid", "2000", "2024-03-01T20:00:00Z"],
        ["e3", "u3", "c@x.com", "order_paid", "500", "2024-03-01T15:00:00Z"],
    ])
    second = run()

    conn = load.connect()
    try:
        in_dwd = conn.execute(
            "SELECT COUNT(*) FROM dwd_events WHERE event_id = 'e3'"
        ).fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM dwd_events").fetchone()[0]
    finally:
        conn.close()
    assert in_dwd == 1, "迟到事件必须补入 dwd_events"
    assert total == 3, "重跑不得重复计入已有事件"

    dws = _dws_by_dt(second)
    assert dws["2024-03-01"]["dau"] == 3
    assert dws["2024-03-01"]["orders"] == 3
    assert dws["2024-03-01"]["gmv_cents"] == 3500
