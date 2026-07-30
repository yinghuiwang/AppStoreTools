# Task Logging & Progress Unification Design

**Date:** 2026-07-30  
**Status:** Approved for planning  
**Branch context:** CLI + Web task observability

## Problem

ASC 任务日志与进度目前是双通道、覆盖不均：

1. **CLI** 以 `print` / `typer.echo` 为主；build 用 `Spinner`（stderr）+ `UploadProgressReporter`；无统一 verbose 分层。
2. **Web** 依赖捕获 **stdout**，再解析 `[PROGRESS:pct:msg]` 写入 `TaskStore`，经 SSE 推送。stderr、多数失败尾部、Spinner 状态进不了任务日志。
3. **进度不准**：build 几乎无结构化进度（UI 靠日志关键词猜 phase）；截图按语言数而非文件数；IAP「已存在跳过」漏打进度；What's New 的 LLM 翻译多在 HTTP 请求线程同步完成，任务抽屉看不到翻译进度。
4. **基础设施脆弱**：PROGRESS 解析在多个 `_start_*_task` 里复制；SSE 约 300s 硬超时；漏接 `capture_stdout` 会导致整段无日志（历史已踩过）。

## Goals

- CLI 与 Web **共用同一套** 日志/进度 API（统一 `TaskReporter`）。
- 覆盖全部任务种类：metadata、screenshots、IAP/订阅、IAP 审核截图、whats-new（含 LLM 翻译）、urls、build/deploy/release、update。
- **阶段标题 + 阶段内细粒度百分比**（全局 `pct` 由阶段权重映射）。
- **可切换详细度**：默认简洁；CLI `--verbose` / Web 任务 `verbose` 展开细节。
- 废弃命令侧手写 `[PROGRESS:…]`；Web 直写 TaskStore，不再依赖字符串协议作为主路径。
- 修复 stderr 缺失、SSE 超时、跳过路径卡进度等问题。

## Non-goals

- 不引入 WebSocket；继续 SSE + TaskStore。
- 不引入 `rich` 或完整 Python `logging` 框架作为用户可见主通道（Reporter 内部可极薄封装）。
- 不重做任务抽屉视觉大改；仅接 phase 字段与详细日志折叠。
- 不改变对外 CLI 命令名与主参数语义。

## Decisions

| Topic | Choice |
|-------|--------|
| 方案 | 统一 `TaskReporter` + 双 sink（CliSink / TaskStoreSink） |
| 范围 | CLI + Web 一起；全任务种类无优先级偏废 |
| 进度模型 | 阶段 + 阶段内细粒度 → 全局 pct |
| 日志详细度 | 默认可切换（简洁 / verbose） |
| 协议演进 | 可较大重构；旧 `[PROGRESS:…]` 迁移期兼容后删除 |
| CLI 是否写 TaskStore | 否；仅 Web 任务挂 TaskStoreSink |
| What's New 翻译 | 翻译进后台任务；预览翻译也返回 `task_id` + SSE |

---

## Architecture

### Core idea

命令层不再直接为 Web「偷偷 print PROGRESS」，而是调用 `TaskReporter`。事件扇出到 sinks：

```text
commands/*  ──►  TaskReporter  ──┬──► CliSink（终端）
                                 └──► TaskStoreSink（Web → SQLite → SSE）
```

- **CLI 入口**：`CliSink` only；尊重 `--verbose`。
- **Web 入口**：`TaskStoreSink(task_id)`；可选调试用 CliSink（默认关）。
- **Spinner / altool**：`progress.py` 继续管子进程 UI/tee；通过回调把阶段与百分比喂给 `TaskReporter`。

### Component boundaries

| Unit | Does | Does not |
|------|------|----------|
| `TaskReporter` | `phase` / `progress` / `log` / `debug` / `done` / `fail` | ASC API、业务循环 |
| `CliSink` | 格式化终端输出；过滤 verbose | 碰 TaskStore |
| `TaskStoreSink` | `append_log` / `set_progress`（含 phase） | 解析字符串协议 |
| `commands/*` | 按真实工作量调用 reporter | 手写 `[PROGRESS:…]` |
| Web `_start_*_task` | 注入 reporter，跑 core | 复制 drain/PROGRESS 解析（迁移后删除） |

### Web data flow

1. API 创建 task → 构造 `TaskReporter(task_id, verbose=…)`。
2. 后台线程跑 core，经 reporter 更新状态。
3. SSE 读 TaskStore；`progress` 事件带 phase 字段；build 页用 `phase_index`，去掉日志关键词启发式。
4. 子进程：tee 到 log 文件；摘要行经 reporter 入库（verbose 才全量）。

---

## Data model & Reporter API

### TaskStore `progress` shape

```text
progress: {
  pct: 0-100,              # 全局百分比（阶段权重汇总）
  msg: string,             # 短状态，如 "上传 3/12 语言"
  phase: string,           # 稳定 id：archive | export | upload | locales | translate …
  phase_label: string,     # 展示文案（可 i18n）
  phase_index: int,        # 1-based
  phase_total: int
}
```

SQLite `task_runs` 增加：`progress_phase`、`progress_phase_label`、`phase_index`、`phase_total`（缺省兼容旧行）。

旧任务无 phase 时：前端 `phase_index=0`，只显示 pct/msg。

### `TaskReporter` API

```python
# 任务开始时声明阶段与权重（缺省阶段则重归一化）
reporter.set_phases([
    ("check", 5, "校验环境"),
    ("locales", 95, "上传本地化"),
])

reporter.phase(phase_id)                          # 进入已声明阶段；pct 到该阶段起点
reporter.progress(current, total, msg=None)       # 阶段内细粒度 → 全局 pct
reporter.log(message, *, level="info")            # 默认可见
reporter.debug(message)                           # 仅 verbose
reporter.done(summary=None)
reporter.fail(message, *, detail=None)            # detail：verbose 或失败尾部上下文
```

`phase_index` / `phase_total` / `phase_label` 由 `set_phases` + 当前 `phase_id` 推导，无需每次手传。

全局百分比：

```text
global_pct = phase_start + (current / total) * phase_weight
phase_start = sum(weights of completed phases)
```

`pct` 单调不减（任务重置除外）。跳过项也推进 `current`，避免进度条卡住。

### Verbosity

| Mode | CLI | Web |
|------|-----|-----|
| Default | 阶段标题 + 进度行 + 关键结果/跳过摘要 | 同上入库；抽屉默认显示这些行 |
| Verbose | 另输出每文件/locale/SKU、子进程关键行 | 创建任务时 `verbose=1`；`debug` 行入库，UI 可折叠「详细」 |

---

## Per-task progress rules

跳过项计入 `current`。无某阶段时重归一化剩余权重。

### Metadata（含 keywords / 纯元数据）

| Phase | id | Weight | Granularity |
|-------|-----|--------|-------------|
| 校验环境 | `check` | 5% | 一次性 |
| 上传本地化 | `locales` | 95% | 按 locale `i/N` |

默认：开始、每语言摘要、结束统计。verbose：字段级变更。

### Screenshots

| Phase | id | Weight | Granularity |
|-------|-----|--------|-------------|
| 扫描/分组 | `scan` | 5% | 一次性 |
| 上传 | `upload` | 95% | **按图片文件** `i/N`（不再只按语言数） |

默认：locale 切换 + 每批结果。verbose：尺寸、display type、删旧图。

### IAP + Subscriptions（同一 Web 任务）

| Phase | id | Weight | Granularity |
|-------|-----|--------|-------------|
| 解析 JSON | `parse` | 5% | 一次 |
| 一次性 IAP | `iap_items` | 40% | 按 item（含「已存在跳过」） |
| 订阅 | `subscriptions` | 55% | 按 subscription |

无订阅时权重并入 `iap_items`。默认每 SKU 一行；verbose：价格点、offer、localization。

### IAP Review Screenshots

| Phase | id | Weight | Granularity |
|-------|-----|--------|-------------|
| 上传 | `upload` | 100% | 按截图文件 |

### What's New（含大模型翻译）

| Mode | Phases | Weights | Granularity |
|------|--------|---------|-------------|
| 仅上传（同一文案 / 已有译文） | `upload` | 100% | 按 locale |
| 翻译 + 上传（CLI `--translate` 或 Web「翻译并上传」） | `translate` → `upload` | **60% / 40%** | 翻译按目标 locale；上传按成功译文 locale |
| 仅预览翻译（Web「预览翻译」） | `translate` | 100% | 按目标 locale |

规则：

1. **翻译进后台任务**：LLM 循环经 `TaskReporter` 报进度（如 `翻译 3/12 · ja`）；失败 locale 记日志并计入进度，不卡死。
2. **预览翻译**：返回 `task_id`；译文写入任务 `result.translations`，前端在 `done` 后通过 `GET /api/task/{id}/status` 读取（不再同步堵死 HTTP）。
3. **已带 `translations` 再上传**：仅 `upload` 阶段。
4. CLI 与 Web 共用同一套阶段规则。

### URLs

| Phase | id | Weight | Granularity |
|-------|-----|--------|-------------|
| 更新 | `update` | 100% | 按「locale × 实际要写的 URL 字段」计数 |

若一次请求只改一种 URL（如仅 support），`total` 即为目标 locale 数。

### Build / Deploy / Release

| Phase | id | Weight | Granularity |
|-------|-----|--------|-------------|
| 归档 | `archive` | 35% | 运行中保持阶段起点 + 心跳日志；结束到阶段末 |
| 导出 | `export` | 15% | 同上 |
| 上传 | `upload` | 50% | 字节/百分比（`UploadProgressReporter` → reporter） |

- 仅 `deploy`（已有 ipa）：跳过 archive/export，upload = 100%。
- 仅 `build`（不上传）：archive+export 重归一化为 100%。
- `phase_index` = 1/2/3 驱动 build 页三步 UI。

### Update（工具自更新）

| Phase | id | Weight | Granularity |
|-------|-----|--------|-------------|
| 下载 | `download` | 70% | 有字节进度则用；否则阶段内保持起点，结束跳到阶段末 |
| 安装 | `install` | 30% | 阶段级（开始 → 完成） |

---

## Error handling, compatibility, migration

### Errors & cancel

- **失败**：`reporter.fail` → CLI 摘要；Web 日志 + `status=error`；失败时可附最近若干行上下文。
- **取消**：循环与阶段边界检查 `cancel_event`；单次 LLM 请求尽量跑完再停。
- **部分成功**：结束 summary 含成功/跳过/失败计数；`status=done` 且 result 带 `partial=true`（或等价约定）。
- **子进程**：失败 tee 尾部经 reporter 入库。

### Compatibility

| Item | Strategy |
|------|----------|
| `[PROGRESS:…]` | 迁移期 Web drain 仍识别；命令改完后删除解析 |
| 旧 TaskStore 行 | 无 phase 时前端回退 |
| SSE 300s 超时 | 任务未终态则续命（心跳续期）；设绝对上限（如 2h）防止僵尸连接 |
| stdout capture | 逐步改为 Reporter 直写；过渡期可双写 |
| CLI 对外 | 命令/主参数不变；输出更结构化；`--verbose` 与 build 对齐并推广 |

### Migration sequence (high level)

1. 落地 `TaskReporter` + sinks + TaskStore/SSE phase 字段 + 前端消费。
2. 逐命令替换 print/PROGRESS；Whats New 翻译移入任务；预览翻译改 task。
3. Build 接 phase + upload 字节进度；去掉关键词猜 phase。
4. 删除 PROGRESS 解析与重复 drain；收紧 SSE 超时策略。
5. 测试与文档（含废弃协议说明）。

---

## Testing

- **Unit**：全局 pct 映射（权重、跳过仍前进、单调不减）；CliSink/TaskStoreSink；verbose 过滤。
- **Commands**：metadata/screenshots/iap/whats-new（含 translate）在 mock 下断言 reporter 调用顺序与计数；build 三阶段 + upload 字节回调。
- **Web**：progress payload 含 phase；SSE；预览翻译 task 结果获取；旧任务无 phase 不崩。
- **Regression**：无真实 ASC/LLM 网络；现有 pytest 保持绿。

---

## Success criteria

- Web 任务抽屉对上述任务均有连续、单调的进度与阶段信息；build 三步与 `phase_index` 一致。
- What's New 翻译过程在任务日志/进度中可见（含预览翻译）。
- 默认日志覆盖开始/关键步骤/跳过/结束摘要；verbose 可见 locale/文件/SKU 级细节。
- stderr/子进程失败尾部出现在 Web 任务日志中。
- 长任务不再因固定 300s SSE 误报超时断开（在任务仍运行时）。
- 命令侧无新增 `[PROGRESS:…]`；主路径不依赖该协议。
