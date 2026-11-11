"""调度入口。"""

import argparse

from etl import extract, load, transform


def run(target_date: str | None = None) -> dict:
    conn = load.connect()
    try:
        load.init_schema(conn)
        watermark = load.current_watermark(conn)

        raw = extract.read_events()
        normalized = []
        for row in raw:
            item = transform.normalize(row)
            item["dt"] = transform.to_partition(item["ts_utc"])
            normalized.append(item)

        added = load.load_ods(conn, normalized, watermark)
        load.rebuild_dwd(conn)
        load.rebuild_dws(conn)

        rows = conn.execute("SELECT dt, dau, orders, gmv_cents FROM dws_daily ORDER BY dt").fetchall()
        return {"loaded": added, "dws": [dict(r) for r in rows]}
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None, help="只加工指定日期")
    args = parser.parse_args()
    result = run(args.date)
    print(f"新增事件 {result['loaded']} 条")
    for row in result["dws"]:
        print(f"  {row['dt']}  DAU={row['dau']}  订单={row['orders']}  GMV={row['gmv_cents']}")


if __name__ == "__main__":
    main()
