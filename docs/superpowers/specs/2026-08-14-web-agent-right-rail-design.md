# Web Agent 右侧图标栏与独立会话生命周期

**状态：** 已批准（chrome / 生命周期；取代 08-13 第 6 节及架构图中的 UI 壳）  
**日期：** 2026-08-14  
**范围：** 把 Agent 从任务日志 dock 的「日志 | Agent」标签中拆出，做成与左栏对等的右侧全局 chrome；日志改为纯 overlay。不改 Agent 后端循环、工具集、apply 门控、SSE 协议。

本文是 [2026-08-13-web-failure-agent-design.md](./2026-08-13-web-failure-agent-design.md) 的 **UI chrome 与会话生命周期补丁**。08-13 第 5、7、8、9、10.1、10.2（自动首轮条件）、12、13.1–13.3 节仍然有效：tool calling、流式事件、`propose_fix` / `apply` 门控、脱敏、replay、错误码均不在此重开。实现时以 08-13 那些节为准，以本文覆盖其第 3.1 UI 目标、第 4 行「UI」、第 6 节全文、第 10 节模板/JS 挂载、第 11 节入口箭头、第 13.4 节 markup 断言和第 14 节中「从 dock 标签进入」的表述。

## 1. 问题

当前 `agent` 分支把 Agent 嵌在 `#task-log-drawer` 里，与日志共用一块右侧槽：

- 打开日志会占用（或切走）Agent 面板；关 dock 会 `abort` Agent 流并拆掉绑定。
- 左栏有「Agent」按钮，用户会以为那是路由，和「钉在右侧的工作台」不一致。
- 切页面、看构建扫描、打开另一条任务日志，都会把对话工作区带走或换绑。

用户要的是：Agent 像左导航一样是 **全局右侧 chrome**；日志只是临时 overlay，绝不替换 Agent。

## 2. 已选方案

**右侧常驻窄图标栏 + 向内展开的对话面板；日志永远 overlay、与 Agent 解耦。**

- 每页 `base.html` 最右侧一条约 48px、仅图标的栏。v1 只有 Agent 一个图标。
- 点图标：向内展开/收起对话面板（挤主列，不改 URL）。展开后钉住：换页、切仪表盘任务、打开日志 overlay、打开构建扫描 `right_panel`，都不收起、不换绑。
- 对话绑定只在 Agent 面板内改：用户搜索并点选另一条 `status=error` 任务，或点「去 Agent 解释」。
- 跨页用 `sessionStorage` 记下开合与绑定；新页从 AgentStore 拉历史渲染，**不**自动开流。

被否决的替代：

| 方案 | 否决原因 |
|------|----------|
| 维持「日志 \| Agent」双标签 | 打开日志会顶掉对话；关 dock 等于关 Agent |
| 独立 `/agent` 整页 | 08-13 已否；打断当前任务页 |
| Agent 留在左栏 nav | 与「右侧工作台」冲突；用户当成路由 |
| 窄屏改成盖住图标栏的 modal | 图标栏是全局入口，不能被自己的面板替换掉 |
| 恢复页面时自动续流 | 刷新/跳转会误打一轮 LLM；只恢复已落库消息 |

## 3. 目标与非目标

### 3.1 目标

- Agent 与日志 DOM、开关、绑定完全分离。
- 日志 **只** 以 overlay 出现；打开/关闭日志不得关闭 Agent、不得改 `sessionId` / `boundTaskId`、不得触发 `bindTask`。
- 右侧图标栏在所有继承 `base.html` 的页面常驻；左栏 **没有** Agent 项。
- 展开的 Agent 是 pinned chrome：换任务行、换路由、构建扫描面板出现，都不 dismiss。
- 跨页恢复：`agentOpen` + `sessionId` + `boundTaskId`；消息来自 AgentStore；恢复路径零次 `POST /api/agent/stream`。
- 保留当前分支已有的：对话区拖拽改宽、Markdown 渲染、SSE 流、方案卡片、apply / 重跑门控（规则仍是 08-13 第 9.5 节）。

### 3.2 非目标

- 不改 `/api/agent/*` 契约、工具列表、plan 状态机、SSE 事件名。
- 不新增 `/agent` 路由，不把主列换成 Agent 整页。
- 图标栏 v1 不放日志、设置或其它图标。
- 不把日志重新 dock 进 `#task-log-dock` 与 Agent 抢槽。
- 不在恢复、换页、仅打开图标栏时自动 `auto_analyze`。
- 不把翻译器改成流式；不向 CLI 加 Agent 命令。

## 4. 决策摘要

| 项 | 选择 |
|----|------|
| Agent 形态 | 全局右侧图标栏 + 可展开对话面板，不是 dock 标签 |
| 左栏 | 删除 `data-open-agent-dock` |
| 日志 | 永远 overlay；独立开关 |
| 绑定 | 钉在原失败任务；仅 Agent 内选任务或「去 Agent 解释」才 `bindTask` |
| 跨页 | `sessionStorage` 三字段；AgentStore 出消息；恢复不开流 |
| 收起 | 只改 `agentOpen`；≠ 停止；≠ apply |
| 导航离开 | abort fetch + `POST /api/agent/stop`；新页只渲染已持久化消息 |
| 后端 | 08-13 全文（除被本文覆盖的 UI 壳） |

## 5. 对 08-13 的覆盖关系

| 08-13 | 本文 |
|-------|------|
| 3.1「第二个标签」 | Agent 是右侧 chrome，不是标签 |
| 4 行 UI「同一 `#task-log-dock`，日志 \| Agent」 | 日志 overlay；Agent 图标栏 |
| 6.1–6.3 dock 标签与左栏 Agent | 整节作废，见第 6–7 节 |
| 6.4「去 Agent 解释」打开 Agent 标签 | 展开右侧面板并 `bindTask`；不关日志 overlay |
| 6.5–6.6 面板内搜索/卡片 | 行为保留，挂到新 DOM |
| 8.4「关 dock / 导航视为停止」 | **仅** 关页、刷新、`pagehide`、点「停止」视为停止。关日志 overlay **不是** 停止。收起 Agent 面板 **不是** 停止 |
| 10 图「浏览器 dock（日志 \| Agent）」 | 见第 10 节 |
| 11.1 打开 dock / Agent 标签 | 展开栏 + 绑定 |
| 11.2 应用后切到日志标签 | 打开日志 overlay；Agent 会话不变 |
| 13.4 双标签与左栏按钮断言 | 见第 13 节 |

未列出的 08-13 条款全部继续有效。

## 6. 布局

### 6.1 三列 chrome

所有页：

```text
┌────────────┬─────────────────────────────┬──────────────┬──────┐
│ 左导航      │ 主内容 + 可选 right_panel     │ Agent 对话    │ 图标 │
│ 无 Agent    │ 日志 overlay 盖在这块上面     │ 仅展开时占宽  │ 栏   │
│ pinned      │                             │ pinned       │ 48px │
└────────────┴─────────────────────────────┴──────────────┴──────┘
```

收起时对话列宽度为 0，图标栏仍在。

图标栏与对话面板是 `body` 的 flex 子级，紧跟在 `main` 之后，与左侧 `aside` 对称。不要放进 `{% block content %}` / `{% block right_panel %}`，也不要放进 `_task_log_drawer.html`。`#task-log-drawer` 仍由 `base.html` include，放在 Agent chrome 之后；它是 `position: fixed`，不占 flex 槽。

图标栏：

- 宽 48px，仅图标，垂直一条。v1 一个按钮：Agent。
- `aria-label` 走现有 `nav.agent`；`aria-pressed` 等于面板是否展开；`aria-controls` 指向对话面板 id。
- 选择器：`[data-agent-rail]` 包住栏，`[data-agent-toggle]` 为图标按钮（不再使用左栏的 `data-open-agent-dock`）。

对话面板：

- `[data-agent-panel]`，默认收起（不占 flex 宽度，`aria-hidden="true"`）。
- 展开后挤主列，不盖住图标栏。默认宽 390px，可拖；下限 280、上限 `min(720, 50vw)`。宽度键固定为 `localStorage` 的 `asc.agentPanel.width`；日志 overlay 继续用现有 `asc.taskLogDrawer.width`，两键互不读写。
- 内含现有 Agent UI：绑定摘要、`data-agent-task-search`、`data-agent-messages`、方案卡片、`data-agent-stop`、`data-agent-stream`。Markdown、流式气泡、卡片门控与当前 `agent-dock.js` 一致，规则仍是 08-13 第 6.6 / 9.5 节。
- 面板内关闭按钮可以没有。若有，必须调用与图标栏相同的 `setOpen(false)`，不得 abort、不得清会话。

日志 overlay：

- 继续用 `#task-log-drawer` + `_task_log_drawer.html`，但 **删除** `role="tablist"`、`data-task-log-tab="agent"`、`#task-log-panel-agent` 及其中全部 Agent 节点。
- **永远** `is-overlay`，不再 `is-docked`，不再 `attachDock` 进 `#task-log-dock`。宽屏也不把日志插进主列右侧槽。
- overlay 只盖主内容与页面 `right_panel`（构建扫描等）。`right` 偏移 = 图标栏 48px +（若 `agentOpen` 则再加上对话面板当前宽度）。不得盖住、卸载或 `display:none` 图标栏与 Agent 面板。
- 关闭：原有关闭按钮、Escape、点击 overlay 外部。这三件事都 **只** 关日志。Escape 在日志打开时不收起 Agent。
- 点 `[data-agent-rail]` 或 `[data-agent-panel]` **不算** overlay 外部点击，因此不会误关日志；点主内容才关 overlay。日志的 focus trap / `inert` 范围不含图标栏与 Agent 面板。

`#task-log-dock`：不再作为日志或 Agent 的停靠槽。`base.html` / `index.html` 里空的 dock 宿主删掉，避免旧 JS 再把日志 dock 进去。

### 6.2 窄屏

断点（现有 1360px 媒体查询）下 **仍然挤布局**：左栏 + 内容 +（可选）展开的 Agent + 图标栏。禁止把 Agent 改成替换图标栏的全屏 modal，禁止 `inert` 掉图标栏。日志 overlay 仍可对主内容做 focus trap，但陷阱范围不含图标栏与 Agent 面板。

### 6.3 构建扫描 `right_panel`

`build.html` 的扫描侧栏（`{% block right_panel %}`、`data-task-log-yield`）出现或刷新时：

- 不得把 Agent 收起、卸载、换绑、abort 流。
- 取消「dock 打开就 `display:none` 扫描栏」这套 yield——那是旧日志 dock 抢槽用的。Agent 与扫描栏同时在时一起挤宽度。

### 6.4 左栏

从 `base.html` 的 `<nav>` 删除 Agent `<button data-open-agent-dock>`。断言：左栏没有 Agent 文案入口，全站没有 `href="/agent"`。

## 7. 开关与绑定

### 7.1 只翻开合的操作

| 操作 | Agent 面板 | 会话 |
|------|------------|------|
| 点图标栏 Agent | toggle `agentOpen` | 不变 |
| 面板内关闭（若有） | 与上同一 toggle | 不变 |
| 打开日志 overlay | 不变 | 不变 |
| 关闭日志 overlay | 不变 | 不变 |
| 点另一条任务的「日志」 | 不变 | 不变（日志自己换 `taskId`） |
| 路由跳转（面板已开） | 新页保持展开 | 见第 8 节恢复 |
| 构建扫描出现 | 不变 | 不变 |

收起面板 **不是** 08-13 的「关 dock」：不 `POST /api/agent/stop`，不 abort 本轮（生成中收起则 token 仍写入消息区，再展开可见），不 apply、不 reject、不删 AgentStore 行。

### 7.2 会改绑定的操作

只有：

1. 「去 Agent 解释」（日志工具栏或仪表盘失败行，`data-open-agent-task`）；
2. Agent 面板搜索结果里点选另一条失败任务。

两者都：`agentOpen=true`（展开）、`bindTask(taskId)`。`bindTask` 语义保持 08-13 第 6.5 / 10.2 节：`GET /api/agent/sessions?task_id=`，有 user/assistant 历史则只 `renderHistory`；没有则 `auto_analyze=true` 开流。搜索框仍只打 `GET /api/agent/failed-tasks`，不经 LLM。

仅点图标栏打开、尚未选任务：空状态 + 搜索，不请求 `/api/agent/stream`。

### 7.3 「去 Agent 解释」

- 展开 Agent 栏并 `bindTask`。
- **不**关闭已打开的日志 overlay；不把 overlay 换成 Agent。
- 不在 running / 完成 / 取消任务上显示该按钮（08-13 6.4）。

### 7.4 Apply 且返回 `new_task_id`

用户点方案「应用」且重跑成功：

- `TaskLogDrawer.open(new_task_id)` 打开 **日志 overlay**（无 tab 参数，抽屉只有日志）。
- Agent `sessionId`、`boundTaskId`、面板开合、消息 DOM **全部不变**。不要对 `new_task_id` 调 `bindTask`。
- 新任务再失败后，用户需再点「去 Agent 解释」才会绑到新 id（08-13 第 12 节该行仍成立）。

### 7.5 生成中导航

`pagehide` / 实际卸载当前页：abort `fetch` 并 `POST /api/agent/stop`（08-13 8.4：本轮 `draft` → `abandoned`，零业务写入）。新页按第 8 节恢复已落库消息，**不得**自动再 POST stream 把停掉的那一轮续上。

## 8. 跨页持久化

`sessionStorage` 键名固定为 `asc.agent.chrome`，值为一份 JSON，字段恰好三个、名称固定：

```json
{
  "agentOpen": true,
  "sessionId": "<uuid 或空字符串>",
  "boundTaskId": "<task id 或空字符串>"
}
```

写入时机：toggle 开合、`bindTask` 得到/清空 id、SSE `session` / `done` 带回 `session_id`。读失败或 JSON 非法则视为 `{agentOpen:false,sessionId:"",boundTaskId:""}`，不抛到页面。

新页加载（`agent-dock.js` 在 `base.html` 每页都会跑）：

1. 图标栏始终渲染。
2. 读 `asc.agent.chrome`。`agentOpen===true` 则展开面板，否则保持收起。
3. 若 `boundTaskId` 非空：`GET /api/agent/sessions?task_id=`，`renderHistory`（含仍为 `pending` 的卡片，08-13 6.6）。用响应里的 `session.id` 覆盖内存与 storage 里的 `sessionId`（服务器为准）。
4. **禁止**在这条恢复路径上设 `auto_analyze` 或调用 `startStream`。即使历史为空也不自动分析——自动分析只允许来自用户点「去 Agent 解释」或在面板里点选失败任务（第 7.2 节）。
5. 无 `boundTaskId`：不 GET sessions；显示空状态；保留 storage 里已有的 `sessionId` 字符串，不清除。用户尚未选任务就点发送：有 `sessionId` 则续写该会话，两者都空则 400（08-13）。

`sessionStorage` 随标签页；关标签即丢 chrome 状态。消息仍在 `~/.config/asc/agent_sessions.db`，下次用同一失败任务再绑可以拉回来。不用 `localStorage` 记 `agentOpen`，避免新标签莫名弹出上次的面板。

面板宽度用 `localStorage`（偏好，不是会话绑定），与 chrome JSON 分开。

## 9. DOM 与脚本职责

| 路径 | 职责 |
|------|------|
| `src/asc/web/templates/base.html` | 去掉左栏 Agent；在 `main` 之后挂载图标栏 + Agent 面板（可用 `{% include "_agent_chrome.html" %}`，不得放进日志 partial）；每页加载 `agent-dock.js` 与 `agent-rail.css` |
| `src/asc/web/templates/_agent_chrome.html` | 仅当从 `base.html` include 时使用：rail + panel markup |
| `src/asc/web/templates/_task_log_drawer.html` | 只剩日志：标题、工具栏、「去 Agent 解释」、输出、跟随、关闭、resize。无 tablist、无 Agent section |
| `src/asc/web/static/agent-dock.js` | 绑定 `[data-agent-panel]`，不再从 `#task-log-drawer` 找消息区。toggle、`sessionStorage`、restore、`bindTask`、stream、卡片。`onDrawerClose` 这种「日志关了就 abort Agent」的钩子删除 |
| `src/asc/web/static/task-log-drawer.js` | 只管日志 overlay。`open` 不接受 `tab:"agent"`。`close` 不调用 Agent abort。去掉 `data-open-agent-dock` 监听。外部点击把 Agent chrome 视为内部 |
| `src/asc/web/static/agent-rail.css` | 图标栏、Agent 面板、拖拽柄、与 overlay 的层叠偏移。Agent 样式从 `task-log-drawer.css` 迁出，不再依赖日志 tab 布局 |
| `src/asc/web/static/dashboard.js` | 失败行仍输出 `data-open-agent-task`；点它只走 Agent `bindTask`，不依赖 dock 标签 |
| `src/asc/web/locales/{zh,en}.json` | 沿用 `nav.agent`、`drawer.explain_with_agent`、`agent.*`；可删仅服务于「日志\|Agent」tab 的文案若已无引用 |

公开 API（E2E 用）：

```js
window.AscAgentDock.bindTask(taskId)
window.AscAgentDock.setOpen(boolean)  // 只翻开合
window.AscAgentDock.getState()        // { open, sessionId, boundTaskId }
```

`TaskLogDrawer.open(taskId, options)` 不再识别 `options.tab`。`currentTaskId()` 仍是 **日志 overlay** 当前任务，与 Agent 的 `boundTaskId` 独立。

## 10. 架构（仅 chrome；编排器不变）

```text
body
  左 aside（nav，无 Agent）
  main（内容、构建扫描 right_panel）
  [data-agent-panel]          ← 展开时 pinned
  [data-agent-rail]           ← 始终 48px
  #task-log-drawer            ← 仅日志 overlay，可与上两者同时存在

Agent 面板
  ├─ POST /api/agent/stream     （08-13 第 8 节）
  ├─ POST /api/agent/stop
  ├─ GET  /api/agent/failed-tasks
  ├─ GET  /api/agent/sessions?task_id=
  ├─ GET  /api/agent/plans/{id}
  ├─ POST /api/agent/apply      → 成功且 new_task_id 则 TaskLogDrawer.open(新id)
  └─ POST /api/agent/reject

日志 overlay
  └─ GET /api/task/{id}/stream  （与 Agent 无关）
```

`WebAgent`、`agent_tools.py`、`agent_store.py`、`routes_agent.py`、`LLMClient.chat_stream` 不因本规格改行为。

## 11. 数据流

### 11.1 解释（无写入）

```text
失败任务 → 「去 Agent 解释」
  → setOpen(true) + bindTask
  → 日志 overlay 若已开则保持
  → 无历史则 POST /api/agent/stream auto_analyze
  → 其余同 08-13 第 11.1 节（draft→pending、卡片、磁盘未改）
```

### 11.2 应用后重跑

```text
点「应用」→ POST /api/agent/apply
  → 门控同 08-13 第 9.5 / 11.2 节
  → 若 new_task_id：打开日志 overlay 看新任务
  → Agent getState() 与点应用前相同
```

### 11.3 跨页

```text
页 A：面板开、已绑定、可能仍在生成
  → 点左栏去页 B
  → pagehide：abort + stop
  → sessionStorage 已有 agentOpen/sessionId/boundTaskId
页 B：展开栏、GET sessions、renderHistory
  → 无 POST /api/agent/stream
```

## 12. 错误与边界（仅 chrome；LLM 错误仍走 08-13 第 12 节）

| 情况 | 行为 |
|------|------|
| storage 不可用或配额 | 本页内存仍 toggle/绑定；刷新后回到收起空状态。不弹窗 |
| restore 时 sessions GET 4xx | 面板按 `agentOpen` 展开；消息区空状态；不 stream |
| 日志 overlay 打开时点图标收起 Agent | 日志继续开；Agent 收起；session 保留 |
| 生成中收起面板 | 流继续；再展开看到已追加 token |
| 生成中换页 | stop；新页只显示 stop 之前已入库的消息 |
| 两套宽度拖拽 | Agent 与日志各记各的，互不覆盖 |

## 13. 测试

禁止真实 LLM。08-13 第 13.1–13.3 节编排器/路由测试保持。下列替换 08-13 第 13.4 节，并改掉仍假设双标签的 E2E。

### 13.1 Markup（TestClient，如 `tests/test_web_server.py`）

首页 HTML：

- 有 `[data-agent-rail]`、`[data-agent-toggle]`、`[data-agent-panel]`。
- `[data-agent-panel]` 内有 `data-agent-stream`、`data-agent-stop`、`data-agent-messages`、`data-agent-task-search`。
- `#task-log-drawer` **没有** `data-task-log-tab="agent"`、没有 `#task-log-tab-agent`、没有 `data-task-log-panel="agent"`。
- 左栏 `nav` **没有** `data-open-agent-dock`，全文没有 `href="/agent"`。
- 「去 Agent 解释」仍以 `data-open-agent-task` 出现在日志工具栏（可 `hidden`）与仪表盘失败行逻辑中。

`task-log-drawer.js` 源码：不含 `/api/agent/stream`，不含 `AscAgentDock.onDrawerClose`。  
`agent-dock.js`：含 `asc.agent.chrome`、`getState`；restore 路径不调用 `startStream` / `auto_analyze`（可用字符串约束：restore 函数体内不得出现 `auto_analyze: true`）。

### 13.2 E2E（Playwright，改 `tests/test_web_agent_e2e.py`）

- **图标 toggle：** 点 `[data-agent-toggle]` 后面板可见且 `getState().open===true`；再点则不可见且 `open===false`；`[data-agent-rail]` 始终可见。
- **开日志不换会话：** 先「去 Agent 解释」拿到 `sessionId`；再打开（或保持）日志 overlay、再关 overlay；`AscAgentDock.getState().sessionId` 与 `boundTaskId` 不变。
- **点图标栏不关日志：** 日志 overlay 已打开时再点 `[data-agent-toggle]` 收起 Agent；`#task-log-drawer.is-open` 仍在。
- **恢复不开流：** 在已有历史的会话上写入 `asc.agent.chrome` 后 `page.reload`；消息出现；spy 到的 `POST /api/agent/stream` 次数为 0。
- **去 Agent 解释不关日志：** 先开失败任务日志 overlay，再点工具栏「去 Agent 解释」；`#task-log-drawer.is-open` 仍在，Agent 面板同时展开。
- **Apply + new_task_id：** 点应用后日志 overlay 打开新任务；`getState().sessionId` 仍是 apply 前的值。
- 删除/改写：断言 `#task-log-tab-agent`、`data-open-agent-dock`、关 dock 即 abort Agent 的旧用例。

## 14. 成功标准

- 任意页右缘都有 48px 图标栏；左栏无 Agent。
- Agent 展开时换页、开日志、开构建扫描，面板仍在、绑定不变。
- 关日志 overlay 等于只关日志。
- 刷新后按 storage 恢复开合与历史，且不自动打模型。
- 不点「应用」则业务文件与任务列表不变（08-13 第 14 节仍要满足）。
- CLI `--help` 无 Agent；测试无真实 LLM 网络。

## 15. 风险

| 风险 | 约束 |
|------|------|
| 旧 E2E/单测仍找 tab 或左栏按钮 | 第 13 节作为合并门槛 |
| 日志 dock 模式残留，宽屏又把抽屉插进主列 | 删除 `#task-log-dock` 宿主；JS 去掉 dock 分支 |
| 关日志误 stop Agent | `TaskLogDrawer.close` 不得碰 Agent 流 |
| 恢复误 auto_analyze | restore 与 `bindTask` 分函数；只有用户选任务的 `bindTask` 可 auto_analyze |
| 扫描栏 yield 把 Agent 或自己藏掉 | 去掉针对 Agent chrome 的 yield |
)
