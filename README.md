# MetricsETL

每日指标管道：把埋点事件从 ODS 增量加工到 DWD 明细和 DWS 日汇总。

## 技术栈

- Python 3.12（纯标准库，无第三方运行时依赖）
- SQLite

## 运行

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt

# 加工 2024-03-01 之前的所有事件（首次全量）
.venv/Scripts/python -m etl.run

# 指定日期重跑
.venv/Scripts/python -m etl.run --date 2024-03-01
```

数据库默认落在 `./warehouse.db`，可用 `METRICS_DB` 覆盖。

## 目录

```
data/events.csv      埋点原始事件（event_id, user_id, email, event_type, amount_cents, ts_utc）
sql/schema.sql       ODS / DWD / DWS 建表语句
etl/extract.py       读取 CSV
etl/transform.py     清洗与字段规范化
etl/load.py          写入与聚合
etl/run.py           调度入口
docs/SPEC.md         指标口径（唯一权威定义）
```

## 指标口径

以 `docs/SPEC.md` 为准，代码实现与其对齐是加工方责任。

## 测试

```bash
.venv/Scripts/python -m pytest -q
```

## 已知问题

- 历史上游埋点有过重复上报，事件去重逻辑待确认。
- 时区口径在早期文档里写过本地时间，后续已统一为 UTC，代码可能未完全同步。
