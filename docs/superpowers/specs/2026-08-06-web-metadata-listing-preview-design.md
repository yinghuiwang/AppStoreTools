# Web 元数据 Listing 预览与细粒度上传设计

**日期：** 2026-08-06  
**状态：** 已批准（对话确认）  
**范围：** `/metadata` Web 页：本地 CSV/截图按语言预览与编辑（写回本地）、与 App Store Connect 同结构 Diff、细粒度勾选上传、以及文本到 CSV / 截图到本地目录的拉取覆盖

---

## 1. 目标与背景

当前 `/metadata` 为「选本地路径 → 勾选大范围（元数据/截图）→ 后台任务 → 日志」模式：

- 无 CSV 按语言结构化预览
- 无截图缩略图预览
- 无语言/字段/设备类型级勾选
- 无 ASC 当前 listing 对照

URLs / What’s New 页已有「从 ASC 拉语言列表」与部分预览模式，可参考但不足以覆盖完整 listing。

**成功标准：**

1. 用户能按语言查看待上传的文本字段与截图，并编辑后写回本地 CSV / 截图目录
2. 用户能按语言、字段、截图（设备类型 / 单张）勾选后上传
3. 用户能以相同行结构对照 ASC 当前内容（文本 Diff + 截图缩略图并排），并可将线上内容拉取覆盖本地

---

## 2. 决策摘要

| 议题 | 决策 |
|------|------|
| 控制粒度 | 语言 + **每语言每字段** + 截图（设备类型 / 单张）；可编辑；截图可替换、可调顺序 |
| 编辑持久化 | 写回本地（CSV + 截图目录文件） |
| ASC 对照 | Diff：同结构标出仅本地 / 仅线上 / 变更 / 相同；再决定上传或拉取 |
| 截图 Diff | 结构 + 左右缩略图并排，人工判断；不做自动「相同」判定 |
| 拉取范围 | 文本写回 CSV；截图按语言×设备类型下载并覆盖本地目录 |
| 架构 | 方案 2：统一 `ListingSnapshot` 行模型；本地工作台 + Diff 工作台；上传复用现有 core 并增加过滤 |

---

## 3. 架构

### 3.1 页面分区（仍在 `/metadata`）

| 区 | 职责 |
|----|------|
| 路径与范围 | 选 CSV / 截图目录、校验可编辑版本（保留现有能力） |
| 本地工作台 | 解析预览、编辑、勾选、写回本地 |
| Diff 工作台 | 拉 ASC、同结构 Diff、勾选后上传或拉取 |

### 3.2 统一领域模型

本地与 ASC 共用同一结构：

```text
ListingSnapshot
├── source: "local" | "asc"
├── version?: { id, versionString, state }   # ASC 侧
└── locales[]: LocaleListing
    ├── locale
    ├── fields: {
    │     name, subtitle, privacyPolicyUrl,          # App Info
    │     description, keywords, supportUrl, marketingUrl  # Version
    │   }
    └── screenshots: {
          [displayType]: ScreenshotItem[]
            ├── id | localPath
            ├── fileName
            ├── thumbUrl
            └── order
        }
```

Diff：

```text
ListingDiff
└── locales[]
    ├── fieldDiffs: per-field ∈ { equal, local_only, asc_only, changed }
    └── screenshotDiffs: per displayType（左右缩略图列表 + 张数；不做内容相等判定）
```

文本 Diff 比较规则：字段值经 trim 后比较；缺失键与空字符串均视为空。双侧皆空 → `equal`；仅一侧非空 → `local_only` / `asc_only`；双侧非空且不等 → `changed`。语言只在一侧出现时，该侧全部非空字段按 only 处理，空字段仍为 `equal`。

### 3.3 后端模块边界

避免继续堆叠 `routes_api.py`，新增聚焦模块（名称可在实现计划中微调）：

| 模块 | 职责 |
|------|------|
| `listing_local.py` | 读/写 CSV；扫描截图目录；替换/排序/删除截图文件；提供本地缩略图访问 |
| `listing_asc.py` | 拉 appInfo + version localizations + screenshot sets；缩略图代理；下载截图到本地 |
| `listing_diff.py` | 纯函数：两 Snapshot → ListingDiff |
| Web API 薄封装 | 上述能力的 HTTP 接口；上传仍走 task runner |

**复用：**

- `parse_csv` / CSV 表头别名（`constants.canonicalize_csv_header`）
- `_upload_metadata_core` / `_upload_screenshots_core`（增加过滤参数）
- `AppStoreConnectAPI` 已有 get/update/screenshot 系列方法
- `_get_available_locales`、metadata check、任务 SSE 模式

### 3.4 写回约定

- **文本：** 显式「保存到 CSV」。存在未保存 CSV 改动时：禁止上传、禁止任何拉取（含截图下载）、更换 CSV/截图路径须确认。截图的排序/替换/删除已直接落盘，不计入「未保存 CSV」状态。
- **截图：** 排序/替换/删除直接改本地目录；排序通过可排序文件名前缀（`01_`、`02_`…）与现有 `_get_sorted_screenshots` 对齐。本地语言子目录 ↔ locale 映射复用 `SCREENSHOT_FOLDER_TO_LOCALE` / 现有 screenshots 命令约定。
- **CSV 写回：** 写回整表；保留未在 UI 展示的列与原有 locale 行顺序；保持 UTF-8-BOM 兼容现有解析。

---

## 4. 本地工作台

### 4.1 进入条件

- 有效 CSV 路径；截图目录可选（未配置则仅文本，截图区提示未配置）
- 解析失败则不进入工作台，展示错误

### 4.2 主视图（按语言一行）

| 列 | 内容 |
|----|------|
| 勾选 | 该语言是否参与上传 |
| 语言 | ASC locale 代码 |
| 字段摘要 | 短预览；展开编辑 |
| 截图摘要 | 各 displayType 张数；展开截图条 |
| 状态 | 未保存 / 已保存 / 校验错误 |

### 4.3 字段编辑

- 可编辑字段：`name`、`subtitle`、`description`、`keywords`、`supportUrl`、`marketingUrl`、`privacyPolicyUrl`
- **勾选粒度是「每语言 × 每字段」**（在该语言展开区内勾选）；未勾选则上传时跳过该语言的该字段（不覆盖 ASC）
- 校验：长度、URL 格式等与 CLI/ASC 已知限制一致；错误则不能进入「已保存」成功态
- 「重新加载」从磁盘重读，丢弃未保存文本编辑

### 4.4 截图编辑

- 按语言 → 按 `displayType` 分组的横向缩略图
- 拖拽排序 → 重写文件名前缀
- 替换：选本地图片覆盖槽位
- 新增：追加到该类型末尾；删除：确认后直接删除文件（本期不做回收站）
- 设备类型勾选；单张默认全选，可取消以只传部分图

---

## 5. Diff / 拉取 / 上传

### 5.1 Diff 进入条件

- 本地 CSV 无未保存改动
- 存在可编辑 ASC 版本（与现有 metadata check 一致）

并行拉取 appInfo localizations、version localizations、screenshot sets。缩略图经本地代理 URL；失败显示占位，可重试，不阻断勾选。

### 5.2 Diff 展示

- 文本：每字段 `相同` / `仅本地` / `仅线上` / `已变更`（变更时展示 local | asc）
- 截图：`语言 × displayType` 左本地 / 右线上缩略图并排
- 筛选：全部 / 仅差异 / 仅本地有 / 仅线上有
- 快捷：「仅勾选有差异项」（只改上传勾选，不自动拉取）

### 5.3 拉取（ASC → 本地）

- **文本：** 勾选语言 + 字段 → 写回 CSV → 刷新本地工作台
- **截图：** 勾选 `语言 × displayType` → 下载该 set 全部图到对应本地子目录，**覆盖该类型现有文件**，按线上顺序写 `01_`… 前缀；强确认
- 拉取与上传互斥；大图集用带进度的后台任务 + 日志

### 5.4 上传（本地 → ASC）

- 仍用现有任务执行 metadata / screenshots core
- 过滤参数（实现时可微调形状，语义固定为）：
  - `locales: string[]`（未出现的语言整语言跳过）
  - `fields_by_locale: { [locale]: string[] }`（该语言要上传的字段名列表）
  - `screenshot_scopes: { locale, displayType, fileNames? }[]`
- 保留 dry-run；上传前要求本地已保存
- 过滤后无可提交项时前端拦截，不建任务

### 5.5 勾选默认值

初次加载：全部语言、全部有值字段、全部本地截图类型（及类型内图片）勾选。

---

## 6. API 草图（实现计划可细化路径）

| 能力 | 方法意图 |
|------|----------|
| 本地 Snapshot | `GET` 解析 CSV + 可选扫截图目录 |
| 保存 CSV | `POST` 提交编辑后的 locales/fields，写回文件 |
| 截图排序/替换/删除/新增 | `POST` 操作本地目录 |
| 本地缩略图 | `GET` 静态或受控文件响应 |
| ASC Snapshot | `GET` 聚合 localizations + screenshot sets 元数据 |
| ASC 缩略图代理 | `GET` 代理线上资源 |
| Diff | `GET`：服务端按给定 CSV/截图路径加载 local Snapshot，再拉 ASC Snapshot，返回 `ListingDiff`（内部调用 `listing_diff`） |
| 拉取文本 | `POST` 选中字段写 CSV |
| 拉取截图 | `POST` 启动下载覆盖任务 |
| 上传 | 扩展现有 `POST /api/metadata/run` 增加 `locales` / `fields_by_locale` / `screenshot_scopes` |

---

## 7. 错误处理

| 场景 | 行为 |
|------|------|
| 无编辑中版本 | Diff/上传不可用，提示与现有 check 一致 |
| CSV 解析失败 / 缺 locale | 不进入工作台 |
| 保存时外部改动文件 | 保存前比对 mtime；冲突则拒绝并提示重新加载 |
| ASC 部分失败 | 文本与截图错误分离；成功部分仍可 Diff |
| 缩略图失败 | 占位 + 可重试 |
| 截图下载部分失败 | 保留已下载文件，报告失败列表 |
| 上传无选中项 | 前端拦截 |
| HTTP 429 | 沿用 API 客户端重试；日志可见 |

---

## 8. 非目标（本期不做）

- 截图像素或 MD5 自动「相同」判定
- 未保存自动写盘
- 创建 ASC 版本（仍要求已有可编辑版本）
- 与 What’s New 页或独立 URLs 页合并为同一流程（本工作台可编辑 URL 字段；专用页可继续使用）
- 截图删除回收站 / 撤销栈

---

## 9. 分期交付

| 阶段 | 内容 |
|------|------|
| P0 | 本地 Snapshot API + 按语言表格只读预览 + 字段展开 |
| P1 | 文本编辑写回 CSV + 语言/字段勾选 + 过滤上传 |
| P2 | 本地截图缩略图、排序、替换、删除 + 截图过滤上传 |
| P3 | ASC Snapshot + 文本 Diff + 文本拉取 |
| P4 | 线上截图缩略图并排 + 截图下载覆盖本地 |

---

## 10. 测试要点

- `listing_diff`：字段四态、缺语言、空字段
- CSV 写回：未编辑列保留、BOM、中文表头别名、行序
- 截图排序重命名与 `_get_sorted_screenshots` 一致
- 上传过滤参数真正缩小对 core 的调用（mock）
- 拉取覆盖后目录文件名与顺序
- 以后端与纯函数测试为主；Web 模板交互按现有仓库习惯补测

---

## 11. 与现有代码的关键衔接点

| 现有 | 用法 |
|------|------|
| `src/asc/web/templates/metadata.html` | 扩展为三区工作台 |
| `src/asc/web/routes_api.py` | 注册新 listing API；扩展 metadata/run |
| `src/asc/utils.py` `parse_csv` | 本地读入 |
| `src/asc/commands/metadata.py` | 过滤上传 |
| `src/asc/commands/screenshots.py` | 过滤上传；排序约定 |
| `src/asc/api.py` | ASC 读本地化与截图；下载 |
| `urls.html` / `_get_available_locales` | 语言列表与勾选 UX 参考 |
| `whats_new.html` | 按语言预览交互参考 |
