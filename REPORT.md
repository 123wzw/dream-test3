# MetricsETL 口径修复报告

对照 `docs/SPEC.md` 逐条核查 `etl/` 四个模块，共确认 7 处不一致，全部已修复。
每条问题均先在 `tests/test_spec.py` 中写了失败测试（修复前 6 条用例全红），修复后全部通过；
`tests/test_functional.py` 的 5 条功能用例保持全绿（共 11 passed）。

## 问题 1：分区日期用了本地时区，不是 UTC

- **违反口径**：SPEC §1「分区字段 `dt` 取事件时间戳的 UTC 日期，不得使用本地时区换算」
- **代码位置**：`etl/transform.py:12`（`to_partition`）
- **当前行为**：`parse_ts(ts_utc).astimezone()` 不带参数，按机器本地时区（本机 UTC+8）换算。
  `2024-03-01T23:30:00Z` 被划到 `2024-03-02`，跨零点的事件全部串分区。
- **正确行为**：`dt` 一律取 `ts_utc` 的 UTC 日期。
- **修复方式**：改为 `parse_ts(ts_utc).astimezone(timezone.utc).date().isoformat()`。
- **测试用例**：`test_partition_uses_utc_date`

## 问题 2：金额解析经过浮点，大整数丢精度

- **违反口径**：SPEC §4「必须使用整数累加，禁止使用浮点数参与求和或中间计算」
- **代码位置**：`etl/transform.py:23`（`normalize`）
- **当前行为**：`int(float(amount_raw))` 先把分转成 float。超过 2^53 的整数（如
  `9007199254740993`）经 float 后丢精度变成 `9007199254740992`。
- **正确行为**：字符串直接按整数解析为分，全程无浮点。
- **修复方式**：改为 `int(amount_raw)`（先 `strip()`，空串按 `"0"` 处理）。
- **测试用例**：`test_amount_cents_parsed_as_integer`

## 问题 3：DAU 按 email 去重，不是按 user_id

- **违反口径**：SPEC §4「当日有任意事件的不同 `user_id` 数量」「同一 `user_id` 绑定多个邮箱时只计 1 人」「不按 email 去重」
- **代码位置**：`etl/load.py:61`（`rebuild_dws`，修复前）
- **当前行为**：`COUNT(DISTINCT email)`，同一用户换邮箱就被计成多人，DAU 虚高。
- **正确行为**：`COUNT(DISTINCT user_id)`。
- **修复方式**：聚合 SQL 改为按 `user_id` 去重计数。
- **测试用例**：`test_dau_counts_distinct_user_id`

## 问题 4：GMV 除以 100.0 用浮点求和，单位错且被截断

- **违反口径**：SPEC §4「单位是分，必须使用整数累加，禁止浮点」「输出到 `dws_daily.gmv_cents`，为整数」
- **代码位置**：`etl/load.py:63` 与 `etl/load.py:71`（`rebuild_dws`，修复前）
- **当前行为**：`SUM(amount_cents / 100.0)` 先转浮点元求和，入库时 `int()` 截断小数。
  例如 3899 分变成 38，这就是业务方看到的「GMV 差了一个数量级」。
- **正确行为**：`SUM(amount_cents)` 整数分直接求和写入 `gmv_cents`。
- **修复方式**：SQL 去掉 `/ 100.0`，Python 侧去掉 `int(...)` 转换，直接写整数结果。
- **测试用例**：`test_gmv_is_integer_sum_of_cents`

## 问题 5：同一 event_id 重复上报被重复计入

- **违反口径**：SPEC §2「同一 `event_id` 只允许存在一条有效记录」、§5「`ods_events`：`event_id` 唯一」「`dwd_events`：一行一个 `event_id`」
- **代码位置**：`etl/load.py:31-43`（`load_ods`，修复前）、`sql/schema.sql`
- **当前行为**：`load_ods` 只按水位过滤，不做 `event_id` 去重，schema 也没有唯一约束。
  上游重复上报（`data/events.csv` 里 `e1004`、`e1018` 各出现两次）在同批次内被插入两条，
  ODS/DWD 各存两份，订单数和 GMV 全部翻倍计入。
- **正确行为**：同一 `event_id` 只保留一条有效记录。
- **修复方式**：`load_ods` 写入前查出已有 `event_id` 集合，库内已有或本批次已见的跳过；
  `sql/schema.sql` 给 `ods_events.event_id`、`dwd_events.event_id` 加 `UNIQUE` 约束。
- **测试用例**：`test_duplicate_event_id_loaded_once`

## 问题 6：水位过滤丢弃迟到事件

- **违反口径**：SPEC §3「允许迟到窗口为 24 小时……不得因为增量水位而丢弃」「迟到事件补入后，其所属 `dt` 分区的 DWS 指标必须同步更新」
- **代码位置**：`etl/load.py:33`（`r["ts_utc"] > watermark`，修复前）、`etl/load.py:26-28`（`current_watermark`）、`etl/run.py:12`
- **当前行为**：只写入 `ts_utc` 大于历史最大水位的事件。迟到事件 `ts_utc` 落在已加工区间内，
  重跑时被直接丢弃，永远不会补进 DWD/DWS。
- **正确行为**：是否入库由 `event_id` 是否已存在决定，与 `ts_utc` 和水位无关；
  迟到事件补入后 DWD/DWS 全量重建，对应分区指标同步更新。
- **修复方式**：删除水位机制（`current_watermark` 及 `load_ods` 的水位参数与过滤），
  改为问题 5 的 `event_id` 幂等去重——既保证迟到数据能补入，也保证重复执行结果不变
  （SPEC §2「全量重跑与增量重跑的最终结果必须一致」）。
- **测试用例**：`test_late_event_within_24h_backfilled`

## 问题 7：DWD 重建不去重，一行一个 event_id 不成立

- **违反口径**：SPEC §5「`dwd_events`：清洗后的明细，一行一个 `event_id`」
- **代码位置**：`etl/load.py:46-53`（`rebuild_dwd`，修复前）
- **当前行为**：`INSERT INTO dwd_events SELECT ... FROM ods_events` 原样全量拷贝，
  ODS 里的重复 `event_id`（历史脏数据或旧库）原封不动进入 DWD。
- **正确行为**：DWD 每个 `event_id` 只有一行。
- **修复方式**：重建时按 `event_id` 去重，保留最早入库的一行
  （`WHERE rowid IN (SELECT MIN(rowid) FROM ods_events GROUP BY event_id)`），
  与问题 5 的入库侧去重形成双保险。
- **测试用例**：`test_duplicate_event_id_loaded_once`（断言 DWD 中 `e1` 只有 1 行）

## 验证结果

- `tests/test_spec.py`：修复前 6 条全部失败，修复后全部通过。
- `tests/test_functional.py`：5 条功能用例继续全绿（合计 11 passed）。
- 用真实 `data/events.csv` 端到端跑两次：首次新增 26 条（27 行 CSV 含 1 条重复），
  第二次新增 0 条，两次 DWS 完全一致：
  - `2024-03-01`：DAU=5，订单=5，GMV=7796 分
  - `2024-03-02`：DAU=8，订单=7，GMV=11594 分

  与手工按 SPEC 口径计算的结果一致。

未改动：`docs/SPEC.md`、`tests/test_functional.py`、数据库路径等运行配置
（`METRICS_DB` / `METRICS_EVENTS` 读取逻辑保持原样）。
