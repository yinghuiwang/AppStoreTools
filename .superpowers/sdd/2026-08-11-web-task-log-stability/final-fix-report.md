# Web Task Log Stability — Final Fix Report

日期：2026-08-12  
基线：`22a38afecd16e7a358bdcd031b4a9c54ce371d29`  
实现提交：`2a02927 fix(web): make terminal publication recoverable`

## 结论

4 个 Important finding 已完成 TDD 修复。聚焦组全部通过；全量测试仅保留任务明确允许的既有失败
`tests/test_subscriptions_validation.py::test_large_screenshot_warns_but_passes`。

## Finding 1：PENDING_COMMIT 不可靠恢复

### 根因

- `TerminalWriteOutcome.__bool__` 把 `PENDING_COMMIT` 当作成功，普通任务会提前通知。
- result-before-status 只保存业务结果，没有保存期望终态；status op claim 后事务失败时，普通任务重启只能被当作中断。
- update `changed=False` 没有 restart marker，却沿用 update 成功猜测；`changed=True` 的 pending 路径在 marker 前也缺少通用 result 恢复契约。

### 修复

- `bool(TerminalWriteOutcome)` 现在仅在 `COMMITTED` 时为真。
- result 写入时增加持久化内部 hint：
  `{"_asc_terminal_recovery": {"version": 1, "status": "<terminal>"}}`，业务字段原样保留。
- `TaskStore` 重启恢复优先读取该 hint；普通 kind、update changed=True/False 均能恢复期望终态。
- `recovery_confirmed` 明确区分“终态未提交但 result 恢复 hint 已持久化”和“result/flush 未持久化”。
- 普通任务只在 `COMMITTED` 后通知；update 仅在 `COMMITTED` 通知。update restart side effect 仅允许 committed/pending durable-result 路径；settled status failure 不触发通知或重启。
- transient final flush failure由 worker 再次执行完整 finalize；仍遵守 flush → result → status。

### 测试

- 真实 SQLite status transaction 在 claim 后注入 commit failure，普通 metadata 任务保持 RUNNING，业务 result 与期望 DONE hint 均持久化；新 `TaskStore` 恢复 DONE。
- update `changed=False` 使用同类 commit failure，确认无通知、marker、restart；新 `TaskStore` 恢复 DONE，且不伪造 `restarted`。
- `PENDING_COMMIT` 的 bool 为 false，普通任务不通知。

## Finding 2：final log flush 软失败后发布终态

### 根因

- `TaskStoreSink.flush()` 吞掉 `False`/异常并返回 `None`。
- `TaskReporter.flush()` 不聚合 sink flush 结果。
- `finalize_task_outcome()` 无条件继续写 result/status。

### 修复

- `TaskStoreSink.flush()` 返回 bool；失败日志重新入队，成功/空队列返回 true。
- `TaskReporter.flush()` 聚合所有 flushable sink；任一 sink 返回 false 或抛错即返回 false；无 flush sink/CLI 兼容路径返回 true。
- finalize 遇到非 durable flush 立即返回 BLOCKED，不写 result/status、不通知、不重启，并输出 task/operation/path stderr。
- worker 对 transient flush failure重试完整 finalize。

### 测试

- 实际 `TaskStoreSink` soft `append_logs=False`：首次 finalize 后 SSE snapshot 仍为 RUNNING、无 result/终态；pending raw error、traceback tail、failure summary 未丢。
- 恢复后第二次 flush 成功，日志以连续 seq 持久化，再发布 ERROR。
- 多 sink soft failure、无 flush sink、worker transient retry 均有覆盖。

## Finding 3：close() writer death TOCTOU

### 根因

`close()` 在 `is_alive()` 与 shutdown enqueue 之间存在窗口；writer 在窗口内退出后，shutdown op 无消费者，调用方等待完整 30 秒且 queue 计数不守恒。

### 修复

- close 使用 50ms 短间隔观察 shutdown op settled、`_writer_stop` 和 thread liveness。
- 检测 writer 死亡后立即 `_abort_writer()`，结算 shutdown/orphan ops，并保持 `task_done()` 计数守恒。
- 正常 close 与重复 close 语义保持不变；后续写仍快速失败。

### 测试

- 确定性覆盖 writer 在初次 liveness check 后、shutdown put 前退出。
- 确定性覆盖 shutdown put 后、下一次 liveness 观察前退出。
- 两条路径均 `<0.8s`，shutdown settled、`unfinished_tasks == 0`；重复 close 幂等。

## Finding 4：zsh raw 验证假阳性

### 根因

- zsh 的小写 `status` 是只读参数，wrapper 在真实命令完成后赋值即提前失败。
- 原测试只检查 exit code 和 cleanup，无法证明成功路径生成三份 capture 或运行到 cmp。

### 修复

- wrapper 全部改用 `exit_code`；系统状态变量改为 `TASK_STATE`；cleanup 使用非保留名。
- 安全 asc/xcodebuild/xcrun/cmp stub 增加独立 sentinel。
- success 断言 archive/export/upload 三份 capture 字节内容及 3 次 cmp。
- release failure精确保留 exit 23，且不生成 capture/cmp sentinel。
- cmp failure由独立 cmp wrapper精确返回 exit 31，证明失败源于 cmp。
- 所有路径确认 wrapper 临时目录清理；仍是一次 release、一次 upload，未调用真实 Xcode/上传。

## RED / GREEN 记录

### RED

1. 新增首批契约测试：
   `pytest -q <11 个精确 node>`  
   结果：`10 failed, 1 passed`。失败分别证明 flush 结果仍为 None、终态仍发布、恢复 hint 缺失、close orphan 未结算、update 仍抛假失败、zsh wrapper 成功/cmp 路径提前 exit 1。
2. worker transient flush retry：
   `pytest -q tests/test_web_task_runner.py::test_worker_retries_terminal_after_transient_final_log_flush`  
   结果：`1 failed`，任务停留 RUNNING。

### GREEN

1. 同一首批精确 node：`11 passed, 1 warning in 4.67s`。
2. close 两条精确竞态：`2 passed in 0.21s`。
3. worker retry、pending no-notify、普通成功：`3 passed in 1.03s`。
4. task log fidelity：`44 passed in 0.72s`。

## 验证命令与精确结果

- 用户点名首批命令包含不存在文件
  `tests/test_web_update_task.py`：pytest exit 4，`file or directory not found`。
  仓库对应现有文件为 `tests/test_urls_update_progress.py` 与 `tests/test_update_cmd.py`。
- 对应首批现有测试：
  `pytest -q tests/test_reporting.py tests/test_web_task_runner.py tests/test_web_tasks.py tests/test_web_server.py tests/test_urls_update_progress.py tests/test_build_progress.py`  
  结果：`374 passed, 26 warnings in 55.52s`。
- 完整计划聚焦组：
  `pytest -q tests/test_reporting.py tests/test_build_progress.py tests/test_update_cmd.py tests/test_web_tasks.py tests/test_web_sse.py tests/test_web_server.py tests/test_web_task_runner.py tests/test_web_task_log_fidelity.py tests/test_web_listing.py tests/test_urls_update_progress.py`  
  结果：`494 passed, 61 warnings in 60.42s`。
- `python -m compileall -q src/asc && git diff --check`  
  结果：exit 0，无输出。
- `ruff check <修改文件>`  
  结果：未执行，环境无 `ruff` 可执行文件（exit 127）；该命令不在强制验证清单。
- 首次全量：`1211 passed, 3 skipped, 2 failed`；除允许失败外发现 webhook 旧断言未接受内部 hint，已修复。
- webhook 精确回归：`1 passed, 1 warning in 0.74s`。
- 最终全量 `pytest -q`：
  `1212 passed, 3 skipped, 1 failed, 75 warnings in 71.66s`；
  唯一失败为允许的
  `tests/test_subscriptions_validation.py::test_large_screenshot_warns_but_passes`，
  消息仍为 `assert "exceeds 5MB" in ''`。

## Deferred Minor / 未解决 concern

- Web phase 事件未持久化：与本次四项终态、flush、close、zsh 契约无阻断关系，deferred。
- 内存模式 first-terminal-wins：本次 SQLite 恢复契约不要求扩张该行为，deferred。
- 既有 subscription 大截图 warning 测试仍失败；任务明确允许，不在本次范围。
- 工作区预先存在未跟踪 `docs/handoffs/`，本次未修改、未提交。

## Follow-up：update soft flush → ERROR 回归（基线 `7d81254`）

### 根因

`_start_update_task` 在 `finalize_task_outcome` 返回 `BLOCKED` 且
`recovery_confirmed=False`（典型：瞬时 final log flush 软失败）时抛出
`TaskTerminalError(..., success=False, restart_blocked=True)`，随后
`_execute_task` 再 `finish(ERROR, …)`。成功更新被误写成 ERROR 并阻断重启，
与普通 kind「不写终态、worker 重试完整 DONE finalize」不一致。

### 修复

- soft `BLOCKED`（无 recovery hint）时：先再跑一次完整 `finalize_task_outcome`
 （对齐 worker `retry_terminal`），成功则继续通知 / restart 副作用。
- 仍 soft-blocked：直接返回成功业务 result，**不**伪造 `restart_blocked` /
  ERROR；允许 `_execute_task` 再 `finish(DONE)`。
- `recovery_confirmed` / `PENDING_COMMIT` / `COMMITTED` 既有副作用门槛不变；
  真实业务失败与 CANCEL 路径未改。

### 验证

- RED：`test_update_retries_done_after_transient_final_flush` 等 3 个精确用例
  在修复前失败（ERROR / `TaskTerminalError`）。
- GREEN：上述 3 用例 + `tests/test_web_task_runner.py` +
  `tests/test_urls_update_progress.py` + `tests/test_web_task_log_fidelity.py`
  → `87 passed`；`python -m compileall -q src/asc` 与 `git diff --check` 通过。
