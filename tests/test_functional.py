"""指标管道功能回归测试。"""

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="metrics-test-")
os.environ["METRICS_DB"] = os.path.join(_TMP, "warehouse.db")

from etl import load  # noqa: E402
from etl.run import run  # noqa: E402


def test_pipeline_runs_and_reports():
    result = run()
    assert result["loaded"] > 0
    assert result["dws"], "DWS 没有产出"


def test_schema_tables_exist():
    conn = load.connect()
    try:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert {"ods_events", "dwd_events", "dws_daily"} <= names


def test_ods_receives_events():
    run()
    conn = load.connect()
    try:
        total = conn.execute("SELECT COUNT(*) FROM ods_events").fetchone()[0]
    finally:
        conn.close()
    assert total > 0


def test_dws_has_expected_columns():
    run()
    conn = load.connect()
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(dws_daily)")]
    finally:
        conn.close()
    assert cols == ["dt", "dau", "orders", "gmv_cents"]


def test_dwd_covers_all_partitions():
    run()
    conn = load.connect()
    try:
        partitions = [r[0] for r in conn.execute("SELECT DISTINCT dt FROM dwd_events ORDER BY dt")]
    finally:
        conn.close()
    assert len(partitions) >= 2
