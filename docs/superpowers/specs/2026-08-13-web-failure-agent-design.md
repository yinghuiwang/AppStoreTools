# Web 失败任务解释 Agent 设计

**状态：** 已批准  
**日期：** 2026-08-13  
**范围：** Web 后台任务失败后的对话式解释、可执行修复提案、用户确认后的本地写入与重跑  

## 1. 问题

Web 任务失败时，用户看到的是原始异常、子进程尾部和 ASC API 错误原文。他们需要的是：

1. 这次失败具体是什么、卡在哪一步；
2. 应改哪些本地文件或配置、怎么改；
3. 若改动能由工具完成，给出可确认的方案；用户选择是否应用，并可选重跑同一类任务。

当前仪表盘「重试」只跳回对应表单页（`retry_path`），不会解释错误，也不会改本地数据。What's New 翻译已复用 Settings 的 `llm.toml` / `LLMClient`，但是非流式、强制 `json_object`、无 tool calling，不能承担这次对话。

## 2. 已选方案

采用 **带 tool calling 的对话式 Agent**（不是 playbook 穷举，也不是只吐 JSON 的诊断器）。

- 失败后由 Agent 阅读该任务的元数据、截断脱敏日志和允许的本地文件，用自然语言解释原因和改法。
- 若问题可在本地自动改，模型调用 `propose_fix` 产出结构化方案；界面在本轮结束后展示确认卡片。用户点「应用」后，服务器才执行本地变更，并可选用现有 `TaskStore` / `start_background_task` 重跑。
- Agent **不**调用 App Store Connect 写接口。对 ASC 的写入只可能发生在用户确认后重跑的既有 Web 任务里（与手动再点一次「上传」相同）。

被否决的替代：

| 方案 | 否决原因 |
|------|----------|
| 仅 playbook / 正则对照表 | 覆盖不了构建、更新、ASC 校验等开放错误 |
| 仅 JSON 诊断器（无对话、无 tool） | 无法追问、无法按日志深入读文件、无法把方案做成可确认卡片 |
| 独立 `/agent` 整页 | 与现有右侧任务日志 dock 抢注意力；用户已在看失败日志 |

## 3. 目标与非目标

### 3.1 目标

- 覆盖全部现有 Web 后台 task kind 的失败解释（见第 5 节）。
- Agent 作为现有右侧任务日志 dock 的第二个标签，不新增整页。
- 复用 Settings 已保存的 LLM 配置；翻译路径行为不变。
- Agent 路径流式输出 token；只读工具在流中暂停执行后继续生成。
- 任何本地写入和任务重跑都必须经过 UI 确认；停止生成永不写盘、永不重跑。
- Prompt、持久化会话和工具返回都脱敏，不含密钥与 `.p8` 内容。

### 3.2 非目标

- 不向 CLI 增加 `asc agent` 或任何 Agent 子命令。
- 不引入 Anthropic 官方 SDK；Settings 已是 OpenAI 兼容 `base_url` + API key。只要该兼容面支持 `stream` 与 `tools` 即可。若某供应商两者都不支持，视为配置错误并提示去 Settings，不为此做第二套协议。
- 不新增登录、账号或远程多租户。Web 仍是本机服务。
- Agent 不直接调用 ASC 创建/修改/删除 API（含元数据、截图、IAP、审核、版本提交）。
- 不把 Agent 做成通用 shell / 任意文件系统助手。
- 不自动应用修复，不提供「记住并自动应用」开关。
- 不在本次把翻译器改成流式或 tool calling。
- 不生成或重绘截图像素；截图类自动修复仅限既有 listing 辅助函数支持的重排、重命名、删除。
- 不为历史任务补造 replay 快照；没有快照的旧任务只解释、给手动步骤和表单链接，不能一键重跑。

## 4. 决策摘要

| 项 | 选择 |
|----|------|
| 形态 | 对话式 Agent + 只读/提案工具；写入与重跑门控 |
| UI | 同一 `#task-log-dock`，标签「日志 \| Agent」；侧栏「Agent」只开 dock |
| LLM | 同一 `llm.toml` / `LLMClient`；Agent 用新的流式+tools 方法 |
| 流 | 独立 `POST /api/agent/stream` SSE，不复用 `/api/task/{id}/stream` |
| 写入 | 仅 `POST /api/agent/apply`；模型 tool 列表不含 `apply_fix` / `rerun_task` |
| 会话 | 本机 SQLite，与 `tasks.db` 并列，不进 git |
| 重跑 | 新建 TaskStore 任务，保留失败任务历史不动 |

## 5. 范围：全部 Web 任务

Agent 可绑定并解释任何 `TaskStore` 中 `status=error` 的任务。现有 kind 与失败后常见本地修复面：

| kind | 含义 | 典型可自动改 | 典型仅手动 |
|------|------|--------------|------------|
| `metadata` | 元数据、关键词、普通截图及组合上传 | CSV 字段、`.asc/config.toml` 的 csv/screenshots 路径、截图文件重排/改名/删除 | ASC 版本不可编辑、凭证失效、截图像素/尺寸不合格 |
| `iap` | 一次性 IAP 与订阅上传 | `iap_packages.json` 允许字段 | ASC 侧已有产品冲突需控制台处理、审核截图像素 |
| `iap-review-screenshots` | IAP 审核截图 | JSON 中的截图路径字段（仍须指向已存在文件） | 缺失的审核图文件本身 |
| `whats-new` | 更新说明上传 | 本地说明文本、locale 字段 | 版本状态不可写 |
| `whats-new-translate` | 更新说明预览翻译 | 无（改 LLM 配置走 Settings） | 供应商错误、缺 LLM 配置 |
| `urls` | 支持/营销/隐私 URL | CSV 中对应 URL 列 | ASC 校验拒绝的远程 URL 内容 |
| `build` | 构建 / 导出 / 上传 | `[build]` 的 project、scheme、output、signing 模式名 | 证书/描述文件缺失、代码编译错误需改 Xcode 工程 |
| `update` | 工具更新（GitHub / pip） | 无 | 网络、权限、指定版本不存在 |
| `listing-pull-screenshots` | 从 ASC 拉截图到本地 | 无（只读拉取失败） | ASC 无图、路径不可写 |

后续经同一 `start_background_task` 注册的 kind 自动可解释；一键重跑要求该 kind 在启动时写入了 replay 快照（第 9.4 节）。

截图上传不是独立 kind，包含在 `metadata`（`include_screenshots`）中；Agent 必须能根据日志区分「元数据失败」与「截图失败」。

## 6. UI

### 6.1 不是独立整页

不新增 `/agent` 路由，不把主内容区换成 Agent 工作台。Agent 活在已经会挤开主内容的右侧任务日志 dock（`#task-log-dock` + `_task_log_drawer.html`，宽约 390px，窄屏 overlay 行为保持不变）。

### 6.2 Dock 标签

Drawer 头部在现有标题旁增加两个标签，文案走 Web i18n：

- **日志**（`drawer.tab_logs`）：现有任务日志 SSE、错误过滤、复制、清空、跟随。
- **Agent**（`drawer.tab_agent`）：会话、流式回复、方案卡片、失败任务搜索。

标签切换只改 dock 内可见面板，不卸载日志 EventSource（切走时暂停跟随即可，切回仍显示同一 `taskId` 的已缓冲日志）。打开 dock 的默认标签：

- 从「日志」/仪表盘日志按钮进入 → **日志**；
- 从侧栏「Agent」或「去 Agent 解释」进入 → **Agent**。

关闭 dock 的方式不变（关闭按钮、Escape、overlay 时点击外部）。关闭不删除会话，也不应用任何 pending 方案。

### 6.3 侧栏「Agent」

在 `base.html` 左侧 `nav` 中、仪表盘与元数据之间加入一项 **Agent**（本产品没有顶栏 header，这项就是「Header/nav Agent」入口）。它是 `<button type="button" data-open-agent-dock>`，不是 `<a href="/agent">`：

- 点击：打开 dock（若关闭）并切到 Agent 标签；
- 不改变当前页面 URL，也不把该项标成与 `/metadata` 同类的路由 `active`；
- dock 打开且当前为 Agent 标签时，该项使用按下态样式，避免用户以为跳进了新页面。

### 6.4 「去 Agent 解释」

失败任务（`status=error`）提供入口，绑定该 `task_id`，打开 Agent 标签，并在该会话尚无用户/助手消息时自动发起第一轮分析（第 10.2 节）。入口位置：

1. Dock **日志** 面板：任务已失败时，工具栏显示按钮「去 Agent 解释」；
2. 仪表盘任务行：在现有「日志」旁增加同名按钮（失败行才显示）。

不在运行中、已完成、已取消任务上显示该按钮。Agent 绑定与搜索只针对 `status=error`；已取消任务不进入下拉，也不自动分析。

### 6.5 Agent 标签内的任务选择

Agent 面板顶部：

- 当前绑定：kind 中文名、短 task id、profile、失败时间；
- 搜索框：调用 `GET /api/agent/failed-tasks`（不经过 LLM），按 kind 标签或 id 前缀过滤；仅 `status=error` 的最近 50 条（当前 cookie profile 的失败任务排在前面，其它 profile 的失败任务仍可搜到并标明 profile）；
- 选中另一失败任务：切换绑定；`GET /api/agent/sessions?task_id=` 若已有会话则加载历史；若无历史则自动第一轮分析。
- 仅打开侧栏 Agent、尚未选任务时：显示搜索与空状态，**不**自动请求 `/api/agent/stream`。

### 6.6 对话区与方案卡片

- 流式 token 追加到当前助手气泡；工具执行时显示只读状态行（例如「正在读取任务日志」），不把原始 tool JSON 铺满屏幕。
- 生成中显示「停止」；停止只中断 LLM 流（第 8.4 节）。
- **方案卡片只在本轮 SSE `done` 之后、且该轮有完整 `propose_fix` 结果时渲染。** 流式过程中即使模型已说出「我将修改 CSV」也不出现「应用」按钮。
- 卡片内容：摘要、每条 mutation 的路径 + 变更前/后（截断显示）、是否建议重跑、原 task id。按钮：**应用**、**忽略**。若方案含 `rerun`，另有勾选「应用后重跑」（默认勾选，因 `propose_fix` 带了 rerun）。
- 用户点「应用」后卡片进入 `applying` → `applied` 或 `apply_failed`。成功且重跑时，前端切到 **日志** 标签并 `TaskLogDrawer.open(newTaskId)`，新任务日志走既有 `/api/task/{id}/stream`。
- 点「忽略」后卡片标记为已忽略，服务器将 plan 标为 `rejected`，不写盘。
- 再次打开该任务会话时，所有仍为 `pending` 的方案重新渲染为确认卡片；`draft` / `abandoned` 不出现应用按钮。

## 7. LLM 复用与分流

Settings 已把多套配置写入 `~/.config/asc/llm.toml`（`llm_configs` + `llm_default`）。Agent 与翻译器都通过 `Config.get_active_llm_config()` 取 `api_key` / `base_url` / `model`。

`LLMClient` 保留现有 `chat()`，行为不变：

- `stream: false`
- `response_format: {"type": "json_object"}`
- 无 `tools`
- 429 / 5xx 最多 3 次

新增 `chat_stream(messages, tools, temperature=0.3)`（方法名固定）：

- `stream: true`
- **不**设置 `response_format`
- 传入 OpenAI 兼容 `tools`（function calling）
- 解析 SSE `data:` 行，向调用方产出增量：`role`/`content` delta、`tool_calls` 增量、结束原因
- 单次 HTTP 超时沿用实例 `timeout`（默认 60s）；429 / 5xx / 连接断开由编排器重试，见第 12 节
- 不把翻译调用改到这条路径

缺 LLM 配置（无 `llm.toml`、无 default、无 `api_key`）时不发起供应商请求，返回可导向 `/settings` 的错误（第 12 节）。

## 8. 流式协议

### 8.1 独立 SSE，不复用任务日志流

任务日志 `GET /api/task/{id}/stream` 继续只服务 TaskStore 日志。Agent 使用：

```http
POST /api/agent/stream
Content-Type: application/json
```

请求体：

```json
{
  "session_id": "<uuid 或省略以新建>",
  "task_id": "<可选，绑定失败任务>",
  "message": "<用户输入；自动分析时可为空>",
  "auto_analyze": false
}
```

用 POST + `StreamingResponse`（`text/event-stream`），不用 `EventSource`：需要请求体。前端 `fetch` + `ReadableStream` 解析帧。复用 `format_sse_event()`，多行 data 仍按现有 SSE 规则拆分。

### 8.2 事件类型

| event | 何时 | data |
|-------|------|------|
| `session` | 流开始 | `{"session_id","task_id"}` |
| `token` | 助手文本增量 | 纯文本碎片（不是 JSON 对象） |
| `tool_start` | 开始执行只读/提案工具 | `{"id","name"}` |
| `tool_result` | 工具结束 | `{"id","name","ok","summary"}`；`summary` 已脱敏短句 |
| `error` | 本轮失败 | `{"code","message"}`，`message` 为 i18n |
| `stopped` | 用户停止 | `{"session_id"}` |
| `done` | 正常结束 | `{"session_id","plan_ids":["..."]}` |

`plan_ids` 仅包含本轮已从 `draft` 晋升为 `pending` 的方案。前端只在收到 `done` 后按这些 id 请求 `GET /api/agent/plans/{plan_id}` 并渲染按钮。`propose_fix` 入库时状态为 `draft`：此时 `POST /api/agent/apply` 返回 409。仅当本轮发出 `done` 时，编排器把本轮 `draft` 改为 `pending`。任何未发出 `done` 的结束（停止、超时、供应商错误、连接断开）把本轮 `draft` 改为 `abandoned`，前端不渲染应用按钮。

心跳：与任务 SSE 类似，约每 3 秒注释行 `: heartbeat`，避免代理断开。绝对时限 10 分钟；超时发 `error`（code=`timeout`）后结束，不写盘。

### 8.3 工具循环（流中）

编排器对供应商请求使用 `stream=true` + tools。循环：

1. 将系统提示、脱敏历史、本轮用户消息发给模型；
2. 把 `content` delta 写成 `token` 事件；
3. 若结束原因为 `tool_calls`：暂停向浏览器发 token；按模型给出的完整 tool call **仅执行只读/提案集合**；把工具 JSON（已脱敏、已截断）追加进消息；回到步骤 1 继续流式；
4. 若结束原因为 `stop` 且无未完成 tool call：写入助手消息，发 `done`。

单轮最多 8 次工具循环。超过则结束本轮并告诉用户「本轮工具次数已用尽，请再问一次」，已完成的 `propose_fix` 仍出现在 `done.plan_ids`。

### 8.4 停止

`POST /api/agent/stop`，body：`{"session_id"}`。

- 设置该会话的取消标志；编排器在下一 chunk / 下一工具边界退出；
- 向流发送 `stopped` 并关闭；
- **永不**调用 `apply_fix` 或 `rerun_task`；
- 本轮未完成的 `propose_fix`（工具尚未返回）丢弃，不入库；
- 本轮已入库的 `draft` 方案标为 `abandoned`。**不**晋升为 `pending`，**不**渲染应用按钮。用户需再开一轮才能重新提案。这样「停止 = 零写入」，也不存在「停完仍能点应用」。

浏览器中止 `fetch`（关 dock、刷新、导航）视为停止：服务器在写 SSE 失败或取消标志时走同一路径。

## 9. 工具

### 9.1 模型可见（流中可执行）

这些函数出现在 `tools` 参数里。服务器在流中直接跑，不弹确认框。

| 名称 | 作用 | 截断与脱敏 |
|------|------|------------|
| `get_task` | 按 id 返回任务：kind、title、profile、status、result、时间、`retry_path`、`has_replay`、以及脱敏后的 replay `params`（无密钥）。不含完整 logs。仅此工具返回 params；仪表盘/HTTP 任务 JSON 仍只多一个 `has_replay` 布尔，不把 params 发给浏览器任务列表。 | result 与 params 字符串脱敏，合计最长 4KiB |
| `list_failed_tasks` | 最近失败任务，默认 20、上限 50。可选 `kind`、`profile`。 | 无日志正文 |
| `get_task_log` | 指定任务日志。默认尾部 400 行；若存在错误行，先收录全部 `isError`/含 traceback 的行（上限 200），再补尾部上下文到合计 400 行。 | 每行脱敏；整段上限 80KiB |
| `get_profile_context` | 当前或任务所属 profile：名称、csv/screenshots/iap 路径、`.asc/config.toml` 的 `[defaults]`/`[build]`。 | **禁止** `issuer_id`、`key_id`、`key_file`、`.p8` 路径、api_key |
| `inspect_local` | 读允许名单内的文本文件或目录列表 | 见 9.2 |
| `propose_fix` | 校验并存储结构化方案，**不修改业务文件** | 见 9.3 |

### 9.2 `inspect_local` 允许名单

参数：`path`（绝对或相对）、可选 `max_bytes`（默认 64KiB，上限 64KiB）。

解析后的路径必须落在下列 **root** 之一（沿用 `listing.local._assert_under_root` 语义，拒绝 `..` 与符号链接逃逸）：

1. 绑定任务所属 profile 的 `csv_path` 文件（解析后的真实路径）；
2. 该 profile 的 `screenshots_path` 目录（目录只返回文件名、尺寸若可得、mtime；**不**把 PNG/JPG 字节送进模型）；
3. 该 profile 的 IAP JSON 路径；
4. 该任务工作目录（启动 Web 时的项目根）下的 `.asc/config.toml`；
5. 任务 replay 或 `[build].output` 下的 `build.log` / `export.log` / `upload.log`；
6. 任务 replay 中的 What's New 源文件路径（若有）。

拒绝：`~/.config/asc/keys/**`、`llm.toml`、`guard.json`、`profiles/*.toml` 中的凭证段、任意 `.p8`、允许名单外的家目录/系统路径。对 `.asc/config.toml`，返回前删除 `[credentials]` 及其键。二进制文件返回 `{binary:true, size, suffix}`，不读内容。

### 9.3 `propose_fix` 方案结构

模型传入的参数由服务器校验后入库。`plan_id` **由服务器生成**，忽略模型自带的 id。

```json
{
  "summary": "zh-Hans 关键词超长，截断至 100 字符并重跑元数据",
  "mutations": [
    {
      "op": "csv_set_fields",
      "path": "data/appstore_info.csv",
      "locale": "zh-Hans",
      "fields": {"keywords": "新关键词"},
      "before": {"keywords": "旧值"}
    }
  ],
  "rerun": {
    "task_id": "<原失败任务 id>",
    "kind": "metadata"
  },
  "manual_steps": []
}
```

允许的 `op`（仅此五种）：

| op | 行为 | 路径限制 |
|----|------|----------|
| `csv_set_fields` | 按 locale 更新 `FIELD_NAMES` 中的字段；写回走既有 `save_local_csv`（保留表头别名与 mtime 检查） | 必须是该 profile 的 csv |
| `json_patch` | 对 IAP JSON 做 RFC 6902 的 `replace`/`add`/`remove`，指针只允许落到产品/订阅的展示与价格字段：`name`、`description`、`reviewNote`、`displayName`、`localizations/*/(name\|description)`、`baseAmount`、`prices/*/price`、审核截图路径字符串 | 必须是该 profile 的 iap JSON |
| `toml_set` | 设置点分键 | 仅项目 `.asc/config.toml` 的 `defaults.csv`、`defaults.screenshots`、`build.project`、`build.scheme`、`build.output`、`build.signing`。`build.signing` 只允许 `auto` 或 `manual`。禁止 `credentials.*`，禁止写入证书名或描述文件路径 |
| `text_replace` | 精确 `before`→`after`；`count` 必须与文件中出现次数一致，否则拒绝 | 仅当该任务 replay 含有 What's New 源文件路径时，且 `path` 必须等于该路径。表单里直接粘贴的文本没有对应文件，不得用此 op，改为手动步骤 |
| `screenshot_fs` | `action`=`rename`\|`delete`\|`reorder`；调用既有 `listing.local` 辅助函数 | 必须在 `screenshots_path` 下 |

`before` 在应用时再读盘核对；不一致则 `apply_fix` 失败（第 12 节），避免覆盖用户在提案之后的手改。

`mutations` 与 `manual_steps` 可同时存在（部分自动、部分手工）。`mutations` 为空且 `manual_steps` 非空是合法方案：卡片只展示步骤，**隐藏「应用」**，仅「忽略」。`rerun` 在无 mutation 时不允许（没有本地变更就不要用 Agent 重跑；用户去原表单）。

无法自动改时（ASC 状态、证书、编译错误），模型不调用 `propose_fix`，只在文本里给手动步骤。

### 9.4 服务器侧写入操作（模型不可见）

`apply_fix` 与 `rerun_task` **不**放入模型 `tools` 列表。流中若仍出现同名 tool call（模型幻觉），编排器返回 tool error：`writes are gated; use propose_fix`，不执行。

它们只由 `POST /api/agent/apply` 在 plan 为 `pending` 时调用（`draft` / `abandoned` / 其它状态均为 409）。`mutations` 为空的方案即使误调 apply 也返回 400，不写盘、不重跑。

**`apply_fix(plan_id)`**

1. 乐观锁：`pending` → `applying`；其它状态返回 409；
2. 按顺序执行 `mutations`；任一步失败：已改的文件不自动回滚（卡片展示失败步；CSV 有 mtime 保护降低撕裂），plan=`apply_failed`，**跳过 rerun**；
3. 全部成功：plan=`applied`。

**`rerun_task(original_task_id)`**

1. 读取原任务 replay；缺失则错误 `no_replay`，不创建任务；
2. `start_background_task`（或该 kind 现有 starter）创建 **新** task id，参数来自 replay（profile、verbose、表单字段）；凭证仍从当前 profile 配置读取，不从 replay 读密钥；
3. 原任务保持 `error`；
4. 返回 `new_task_id`。

为使重跑可行，所有经 `start_background_task` 启动的 Web 任务在 create 时写入脱敏 `replay`：

```json
{
  "kind": "metadata",
  "profile": "myapp",
  "verbose": false,
  "params": {
    "csv_path": "...",
    "screenshots_dir": "...",
    "include_metadata": true,
    "include_screenshots": true,
    "dry_run": false,
    "locales": ["zh-Hans"],
    "fields_by_locale": null,
    "screenshot_scopes": null
  }
}
```

`params` 只含该 kind 表单里的非密钥字段（路径、开关、locale 列表、build 的 project/scheme/destination/ipa 路径、`signing` 为 `auto` 或 `manual`、IAP 文件路径、What's New 文件路径）。若 What's New 来自表单粘贴而非文件，replay 可存 `text` 字段，上限 8KiB，仅供解释，不能作为 `text_replace` 目标。禁止写入 `issuer_id`、`key_id`、`key_file`、`api_key`、Authorization、证书文件内容。`replay` 存在 `task_runs.replay_json` 新列（TEXT，JSON 对象或 NULL）。历史行该列为 NULL，视为无快照。

允许名单与 `apply_fix` 的路径校验一律以**被绑定任务的 profile** 为准，不用侧栏 cookie 当前 app。cookie 只影响失败任务搜索的排序。

`POST /api/agent/apply` 请求体：

```json
{
  "plan_id": "<uuid>",
  "rerun": true
}
```

`rerun=true` 仅当 plan 自带 `rerun` 且 `apply_fix` 成功时才调用 `rerun_task`。`rerun=false` 只改本地文件。忽略按钮走 `POST /api/agent/reject`，body：`{"plan_id"}`，仅 `pending` 可 reject（否则 409）。

同一 `plan_id` 并发 apply：第二个请求 409。已 `applied` / `rejected` / `abandoned` / `apply_failed` 的方案不能再 apply。

### 9.5 写入门控（硬规则）

下列规则同时成立，实现与测试都必须按此断言：

1. 模型 `tools` 列表只有第 9.1 节六个函数。没有 `apply_fix`，没有 `rerun_task`。
2. 流式回合里服务器只执行这六个函数。幻觉调用写入工具时只回 tool error，磁盘与 TaskStore 不变。
3. `propose_fix` 只写 `agent_sessions.db` 的 `plans` 行（状态 `draft`），**不**改 csv / json / toml / 截图 / `tasks.db` 业务任务。
4. 业务文件变更与新建 Web 任务的**唯一**入口是用户点击卡片「应用」触发的 `POST /api/agent/apply`。
5. `apply` 仅当 `plans.status == pending` 时执行；先标 `applying`，成功才 `applied`。`draft` 不可 apply。
6. `rerun_task` 只在同一次 `apply` 里、且 `apply_fix` 全部成功、且请求 `rerun=true`、且 plan 含 `rerun` 时调用。`apply_fix` 失败则跳过 rerun。
7. 只有 SSE `done` 把本轮 `draft` 晋升为 `pending`。「停止」、超时、缺 LLM、供应商错误不得 `done`，把本轮 `draft` 标 `abandoned`，且不得调用 `apply`。
8. 没有「自动应用」开关、cookie 或二次确认以外的隐式路径。

「本地写入」在本文中指业务文件与新 TaskStore 任务，不包括 AgentStore 里的会话/方案行。

## 10. 架构与组件

```text
浏览器 dock（日志 | Agent）
  │
  ├─ 日志标签 ── GET /api/task/{id}/stream ── TaskStore
  │
  └─ Agent 标签
        ├─ POST /api/agent/stream  ── WebAgent 编排器
        │                              ├─ LLMClient.chat_stream
        │                              ├─ 只读工具 / propose_fix
        │                              └─ AgentStore（会话、消息、pending 方案）
        ├─ POST /api/agent/stop
        ├─ GET  /api/agent/failed-tasks
        ├─ GET  /api/agent/sessions?task_id=
        ├─ GET  /api/agent/plans/{plan_id}
        ├─ POST /api/agent/apply   ── apply_fix →（可选）rerun_task → TaskStore
        └─ POST /api/agent/reject
```

Web 进程内单编排器；CLI 不引用这些模块。

| 路径 | 职责 |
|------|------|
| `src/asc/llm.py` | 保留 `chat()`；新增 `chat_stream()` |
| `src/asc/web/agent.py` | `WebAgent`：组消息、工具循环、停止标志、脱敏后写入会话 |
| `src/asc/web/agent_tools.py` | 工具实现、允许名单、`propose_fix` 校验 |
| `src/asc/web/agent_store.py` | SQLite：sessions / messages / plans |
| `src/asc/web/agent_redact.py` | 在 `notifications` 已有规则上增加 `.p8`、issuer/key_id、`BEGIN PRIVATE KEY` 块 |
| `src/asc/web/routes_agent.py` | `/api/agent/stream`、`/stop`、`/apply`、`/reject`、`/failed-tasks`、`/sessions`、`/plans/{id}`，由 `server.py` 挂载 |
| `src/asc/web/tasks.py` / `task_runner.py` | create 时写入 `task_runs.replay_json` |
| `src/asc/web/templates/_task_log_drawer.html` | 标签、Agent 面板、流式区域、停止按钮占位 |
| `src/asc/web/static/task-log-drawer.js` | 标签切换、打开时选标签、失败时「去 Agent 解释」 |
| `src/asc/web/static/agent-dock.js` | 会话 UI、POST 流解析、卡片、停止、apply/reject |
| `src/asc/web/templates/base.html` | 侧栏 Agent 按钮 |
| `src/asc/web/locales/{zh,en}.json` | 全部 Agent/dock 文案 |
| `src/asc/web/templates/index.html` + `dashboard.js` | 失败行「去 Agent 解释」 |

What's New 翻译继续只走 `routes_api` + `LLMClient.chat()`，不经过 `WebAgent`。

### 10.1 会话存储

路径：`~/.config/asc/agent_sessions.db`，可用 `ASC_WEB_AGENT_PATH` 覆盖（测试用）。WAL、单 writer、显式关闭连接，对齐 TaskStore 的连接纪律，但不塞进 `tasks.db`，以免任务日志迁移与 Agent 方案锁耦合。

表：

- `sessions(id, task_id, profile, created_at, updated_at)`
- `messages(session_id, seq, role, content, tool_name, tool_call_id, created_at)`
- `plans(id, session_id, turn_seq, status, summary, mutations_json, rerun_json, manual_steps_json, error, new_task_id, created_at, settled_at)`

`plans.status`：`draft` | `pending` | `applying` | `applied` | `rejected` | `abandoned` | `apply_failed`。

`draft`：`propose_fix` 刚校验入库，本轮尚未 `done`，不可 apply。  
`pending`：本轮已 `done`，等待用户点「应用」或「忽略」。

同一 `task_id` 复用同一 session（再分析续写）。消息在写入前脱敏。发给模型时只带最近 20 条消息 + 系统提示 + 本轮绑定任务的 `get_task` 摘要；更早的 tool 结果可再截断到 2KiB。

系统提示固定要求：用 UI 语言（`request.state.lang`）回答；先解释这次失败；可改则 `propose_fix`；不可改则只给手动步骤；禁止声称已经改文件或已重跑；禁止索要或复述密钥。

### 10.2 自动第一轮

条件：入口带 `task_id`，该 session 还没有 `role=user` 或 `role=assistant` 的消息。前端 `POST /api/agent/stream`：`auto_analyze=true`，`message` 可空。编排器注入一条内部用户消息（聊天里显示 i18n `agent.auto_analyze_label`，中文为「请解释这次失败」）：绑定 task id，要求先 `get_task` + `get_task_log`，必要时 `inspect_local`，再解释；能修则 `propose_fix`。

用户之后的追问带同一 `session_id` 与可选 `message`。

## 11. 数据流

### 11.1 解释与提案（无写入）

```text
失败任务
  → 用户点「去 Agent 解释」
  → 打开 dock / Agent 标签 / 绑定 task_id
  → POST /api/agent/stream (auto_analyze)
  → WebAgent 组 prompt（脱敏）
  → LLMClient.chat_stream(tools=只读+propose_fix)
  → 只读工具 → TaskStore / 允许名单文件
  → propose_fix → AgentStore plans(draft)
  → SSE token / tool_* / done{plan_ids}（此时 draft→pending）
  → 前端渲染文本 + 方案卡片（此时磁盘未改）
```

### 11.2 确认应用与重跑

```text
用户点「应用」（可选勾选重跑）
  → POST /api/agent/apply
  → 仅当 status=pending：applying
  → apply_fix（允许名单 mutation）
  → 失败：apply_failed，响应错误，停止
  → 成功且 rerun=true：rerun_task → 新 TaskStore 任务
  → applied + new_task_id
  → 前端切到日志标签，打开新任务 SSE
```

用户点「忽略」→ `rejected` → 结束。

## 12. 错误处理

| 情况 | 行为 |
|------|------|
| 无 LLM 配置或缺少 api_key | 不调用供应商。SSE 或 JSON `error.code=llm_not_configured`，文案指向 Settings（`/settings`）。不写业务文件。 |
| 供应商 429 | 遵守 `Retry-After`（缺省 1s），最多 3 次；仍失败则 `error.code=llm_rate_limited`。本轮未 `done`：未完成 propose 丢弃，已入库本轮 `draft` 标 `abandoned`。不写业务文件。 |
| 供应商 5xx、超时、连接断开 | 等待 1s 后重试，最多 3 次；仍失败 `error.code=llm_unavailable`。结束方式与 429 相同：无 `done` 则放弃本轮 `draft`。不写业务文件。 |
| 流中途断开 | 同停止：无 apply、无 rerun；未完成 propose 丢弃；已入库本轮 `draft` 标 `abandoned`。 |
| 只读工具失败（任务 404、路径拒绝、读盘错误） | `tool_result.ok=false` + 短原因；模型继续解释。不中止整个会话。 |
| `inspect_local` 路径越权 | 不读文件；工具返回拒绝原因。 |
| `propose_fix` 校验失败 | 工具返回字段级原因；不入库。模型可改后再提。 |
| 不可自动修复 | 无卡片；助手文本给手动步骤和 `retry_path`（若有）。 |
| `apply_fix` 失败（before 不匹配、mtime、越权、JSON 指针非法） | plan=`apply_failed`；**不** rerun；卡片展示失败步。用户可回 Agent 继续问。 |
| `rerun_task` 失败（无 replay、kind 未知、create 失败） | 本地 mutation 已成功则保持 `applied`，响应中 `rerun_error`；提示去原表单或回 Agent。 |
| 重跑后的新任务再失败 | 新任务日志在日志标签；用户可再「去 Agent 解释」绑定 **新** task id。 |
| 未选 profile | 解释流只要带了 `task_id` 就不要求 cookie profile（用任务上的 profile 做允许名单）。`apply` 同样用任务 profile。无 `task_id` 且无 session 的 stream 返回 400。 |
| Guard 拒绝重跑 | 与手动再跑同一 starter 的行为一致；错误进入新任务或 apply 响应，不绕过 Guard。 |

停止、超时、供应商错误、缺配置：**零业务写入、零新任务**。唯一写入入口是用户确认后的 `POST /api/agent/apply`。

## 13. 测试（无真实 LLM）

禁止网络访问真实模型供应商。`LLMClient.chat_stream` 与编排器一律 mock。

### 13.1 流与 tool_calls

- Mock 供应商先返回带 `tool_calls` 的 chunk，再返回文本；断言编排器暂停、执行 `get_task`、把工具结果送回、再转发后续 `token`。
- Mock 幻觉调用 `apply_fix`：断言未改任何文件、未 `TaskStore.create`，工具结果为 gated 错误，最终可 `done`。
- 截断与脱敏：含 `-----BEGIN PRIVATE KEY-----`、`.p8` 路径、`api_key` 的日志进入 `get_task_log` 后，写入会话和发给 mock 的 messages 都不含原文。

### 13.2 编排器门控

- `propose_fix` 入库 `draft`，工作目录文件字节不变；对 `draft` 调用 apply 得 409。
- 模拟流 `done` 后同 id 变为 `pending`，此时 apply 才允许。
- 无 `POST /api/agent/apply` 时，即使 plan 为 `pending` 也不写盘、不重跑。
- `apply` 成功路径：临时 csv 被改；`rerun=true` 时 TaskStore 新任务 kind/profile 与 replay 一致，旧任务仍为 error。
- `apply_fix` 中途失败：`rerun` 未被调用（mock starter 调用次数为 0）。
- `stop`：本轮 `draft` 变为 `abandoned`；随后 apply 返回 409。
- 并发二次 apply 同一 `pending` plan：一次成功，一次 409。
- 缺 LLM 配置：不实例化会发 HTTP 的客户端（或 mock 断言零请求）。

### 13.3 路由

- `POST /api/agent/stream` 返回 `text/event-stream`，事件名仅允许第 8.2 节集合。
- 与 `GET /api/task/{id}/stream` 并存、互不替代。
- `POST /api/agent/apply` / `reject` / `stop` 的成功与校验错误状态码。
- `GET /api/agent/failed-tasks` 只返回 `status=error`；`GET /api/agent/plans/{id}` 始终包含 `status` 字段；`draft` 与 `abandoned` 的 apply 均为 409。
- TestClient，不启真实供应商。

### 13.4 前端 markup

在 `tests/test_web_server.py`（或紧邻测试）断言：

- `_task_log_drawer.html` / 页面 HTML 含 `data-task-log-tab="logs"` 与 `data-task-log-tab="agent"`；
- `base.html` 含 `data-open-agent-dock` 的侧栏按钮，且 **没有** `href="/agent"` 的主导航链；
- 失败任务入口：`data-open-agent-task`（按钮的 `data-task-id` 为任务 id）；
- Agent 面板含 `data-agent-stream`、`data-agent-stop`、`data-agent-messages`、`data-agent-task-search`。

不强制浏览器 E2E；静态 HTML/JS 字符串断言即可。

## 14. 成功标准

- 任意现有 Web 失败任务可从日志 dock 或仪表盘进入 Agent，并自动完成第一轮解释（mock LLM 下走到 `done`）。
- 用户不点「应用」则本地 csv/json/toml/截图文件与任务列表与操作前一致。
- 点「应用」且勾选重跑：允许名单内文件变更 + 新 TaskStore 任务；日志标签能打开新任务流。
- 「停止」或供应商失败后无新文件写入、无新任务。
- 翻译器仍走非流式 `json_object` `chat()`。
- CLI `--help` 无 Agent 命令。
- 测试套件无真实 LLM 网络。

## 15. 风险与约束

| 风险 | 约束 |
|------|------|
| 模型在文本中谎称已修复 | 系统提示禁止；UI 只在 `done`+pending plan 后给按钮；无 apply 则文件不变（测试锁定） |
| 模型请求改密钥或 ASC | 工具允许名单 + 模型不可见写入工具 + apply 再校验路径与 op |
| 长日志撑爆上下文 | `get_task_log` 400 行 / 80KiB；会话 20 条 |
| 与任务日志 SSE 混淆 | 独立路径与事件名；前端两套解析器 |
| 旧任务不能重跑 | 明确无 replay 则只解释；不伪造参数 |
| 方案提出后用户手改文件 | apply 时核对 `before` / csv mtime，失败则跳过 rerun |
