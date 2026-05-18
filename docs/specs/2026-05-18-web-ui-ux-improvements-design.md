# Web UI 体验优化设计文档

**日期：** 2026-05-18
**分支：** feat/web-ui

---

## 目标

在现有 Web UI 基础上补充五项功能，提升操作反馈的完整性和信息密度：

1. Guard 绑定详情展示
2. 表单内 profile 切换统一化
3. 验证环境结果分级展示
4. 上传进度百分比
5. 任务历史记录

---

## 功能设计

### 1. Guard 绑定详情展示

**位置：** 设置页 `/settings`

**数据来源：** `Guard.get_status()` 返回完整 bindings 数据，结构为：

```json
{
  "enabled": true,
  "bindings": {
    "machine": { "<fingerprint>": { "app_id": "...", "app_name": "...", "bound_at": "..." } },
    "ip":      { "<ip>":          { "app_id": "...", "app_name": "...", "bound_at": "..." } },
    "credential": { "<key_id>":   { "app_id": "...", "app_name": "...", "issuer_id": "...", "bound_at": "..." } }
  }
}
```

**展示逻辑：** 按 app 分组，将 machine / ip / credential 三类绑定合并到同一 app 行。当前激活的 profile 排第一并标 ★。

**展示格式（每行一个 app）：**

```
★ myapp    凭证 ABCD1234   机器 a1b2c3d4...   IP 1.2.3.4   绑定于 2026-05-18 10:23
  staging  凭证 EFGH5678   机器 a1b2c3d4...   IP 1.2.3.4   绑定于 2026-05-17 09:11
```

**API 变更：**
- `GET /api/guard/status` 改为返回结构化 JSON（当前返回 HTML 片段）
- 新增字段 `current_profile`，用于前端标记 ★
- 机器指纹只传前 8 位 + `...`（后端截断）

**前端：** settings.html 用 Alpine.js `x-init` fetch 数据，渲染绑定表格。

---

### 2. 表单内 profile 切换统一化

**问题：** metadata.html 和 build.html 表单内各有一个 profile 下拉框，与顶部 App 切换器行为不一致，切换时不刷新页面导致字段值不更新。

**方案：** 移除两个表单内的 profile `<select>` 字段。表单提交时 profile 从 cookie 读取（后端 `_get_profile_context` 已支持）。用户统一通过侧边栏 App 切换器切换 profile。

**后端变更：**
- `POST /api/metadata/run` 和 `POST /api/build/run` 的 `profile` 参数改为从 cookie 读取，不再从 Form 接收
- `POST /api/metadata/check` 同上

---

### 3. 验证环境结果分级展示

**当前问题：** 验证结果是纯文字，无视觉区分。

**API 变更：** `POST /api/metadata/check` 返回结构扩展：

```json
{
  "ok": true,
  "level": "success",
  "message": "环境正常",
  "detail": {
    "version": "1.2.3",
    "state": "PREPARE_FOR_SUBMISSION",
    "app_name": "MyApp"
  }
}
```

`level` 取值：
- `success` — 版本可编辑，绿色
- `warning` — 版本存在但状态不可编辑（已提交审核等），黄色
- `error` — 连接失败或配置缺失，红色

**前端：** `#check-result` 区域根据 level 渲染带颜色背景的卡片，显示 message + detail 中的版本号和状态。

---

### 4. 上传进度百分比

**约定：** 后端在 stdout 输出特定格式行触发进度更新：

```
[PROGRESS:45:元数据 5/11 语言]
[PROGRESS:72:截图 8/11 语言]
```

**实现：**
- `_upload_metadata_core` 和 `_upload_screenshots_core` 在每处理完一个语言后 print 上述格式
- drain 线程用正则 `\[PROGRESS:(\d+):(.+)\]` 匹配，匹配到则写入 task_store 的 `progress` 字段（`{"pct": 45, "msg": "元数据 5/11 语言"}`），不写入 logs
- SSE 流检测到 progress 字段变化时发送 `progress` 事件

**前端：** 进度条显示百分比数字，进度条下方显示当前步骤描述文字。

**task_store 变更：** 新增 `progress` 字段 `{"pct": 0, "msg": ""}` 到 task 记录。

---

### 5. 任务历史记录

**位置：** 首页仪表盘 `/`，替换现有简单列表

**展示：** 最近 20 条任务，表格形式：

| 类型 | Profile | 状态 | 时间 | 操作 |
|------|---------|------|------|------|
| 元数据上传 | myapp | ✅ 完成 | 05-18 10:23 | 查看日志 |
| 构建上传 | staging | ❌ 失败 | 05-18 09:11 | 查看日志 / 重试 |

- 点击「查看日志」展开折叠面板，显示完整日志
- 「重试」仅失败任务显示，点击跳转对应表单页
- 状态颜色：绿色完成、红色失败、蓝色运行中、灰色等待
- 会话内有效，重启清空

**task_store 变更：** task 记录新增 `profile` 字段，在 `_start_metadata_task` 和 `_start_build_task` 创建时传入。

**首页轮询：** 有运行中任务时，每 3 秒用 HTMX 刷新任务列表区域（`hx-trigger="every 3s"`）。

---

## 文件变更清单

**修改：**
- `src/asc/web/tasks.py` — task 记录新增 `profile`、`progress` 字段
- `src/asc/web/routes_api.py` — guard/status 返回 JSON；metadata/check 返回结构化结果；metadata/run 和 build/run 从 cookie 读 profile；drain 线程解析 PROGRESS 格式
- `src/asc/web/templates/settings.html` — Guard 绑定详情表格
- `src/asc/web/templates/metadata.html` — 移除 profile 下拉；验证结果分级渲染；进度条显示百分比
- `src/asc/web/templates/build.html` — 移除 profile 下拉；进度条显示百分比
- `src/asc/web/templates/index.html` — 任务历史表格 + 日志折叠面板

**修改（上传核心逻辑）：**
- `src/asc/commands/metadata.py` — `_upload_metadata_core` 输出 PROGRESS 格式
- `src/asc/commands/screenshots.py` — `_upload_screenshots_core` 输出 PROGRESS 格式

**新增测试：**
- `tests/test_web_server.py` — 追加 guard/status JSON 格式、metadata/check 分级、progress 解析测试

---

## 不在范围内

- task_store 持久化（重启后历史清空，属于后续迭代）
- 重试功能的参数回填（跳转到表单页，不预填参数）
