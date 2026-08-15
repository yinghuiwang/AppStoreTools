# Web 元数据语言码搜索弹窗设计

**日期：** 2026-08-15  
**状态：** 已批准（对话确认）  
**范围：** `/metadata` Web 工作台：只读查询 App Store Connect 支持的地区语言码；点击复制 `code`。不改 CSV、不改上传范围、不创建 localization。

---

## 1. 目标与背景

`/metadata` 工作台已能按 CSV 行预览、勾选并上传，但仓库里没有 App Store Connect 的**全量语言码目录**。现有 `CSV_LOCALE_TO_ASC` 只有约 10 条简写映射；`_get_available_locales`（`src/asc/web/routes_api.py`）返回的是**当前可编辑版本上已有的 version localizations**，不是 Apple 支持列表。

用户需要在上传工作台里随时查阅官方语言码（如 `zh-Hans`），搜索后复制，方便填写 CSV。本功能是查阅参考，不是选语言去改 listing。

**成功标准：**

1. 在 `/metadata` 打开弹窗即可搜索全量语言码（不依赖 CSV 是否已加载）
2. 有凭证且存在可编辑版本时，已出现在该版本上的语言带「已有」标记
3. 点击一行只复制 `code`（例如 `zh-Hans`），不写 CSV、不改 `locales_json` / 勾选、不关弹窗
4. App Store Connect 不可用时弹窗仍能打开并搜索复制

---

## 2. 决策摘要

| 议题 | 决策 |
|------|------|
| 用途 | 只查不改：不改动工作台、CSV、上传范围 |
| 数据 | 静态全量目录 + 标记当前可编辑版本已有语言 |
| 点击 | 只复制 `code`（不是 `DisplayName(code)`） |
| 架构 | 后端返回目录 + `present`；Alpine modal 挂在 `/metadata` |
| 已有语言来源 | 复用 `_get_available_locales`（version localizations），不是 appInfo localizations，也不是现场拉 Apple enum |
| ASC 降级 | 仍 200 + 全量目录；全部 `present: false`；`presenceAvailable: false` |

---

## 3. 架构

```
点击「语言码」
  → Alpine modal 打开
  → 若内存未加载：GET /api/metadata/locales（cookie `asc_profile`，与 metadata check 同一凭证上下文）
  → 服务端 list_locales() 读包内 JSON（无网络）
  → 若能连 ASC 且有可编辑版本：_get_available_locales 匹配 code → present
  → 前端按查询词过滤、按 code 排序、展示、复制
```

搜索的**唯一权威来源**是仓库内静态文件，不是 App Store Connect 的运行时枚举。Apple 日后增删语言时，改 JSON 并发版即可。

### 3.1 模块边界

| 路径 | 职责 |
|------|------|
| `src/asc/data/asc_locales.json` | 全量目录：`code` / `name_en` / `name_zh`；按 `code` 唯一 |
| `src/asc/locales_catalog.py` | 读 JSON、校验、`list_locales()`、`filter_locales()`；**禁止网络**。`list_locales(path=None)` 默认读包内文件；测试可传入临时路径。每次调用都读盘并校验（50 条，不设进程缓存），避免单测无法模拟损坏文件。 |
| `GET /api/metadata/locales` | 叠 `present` + `presenceAvailable`；目录损坏才 500 |
| `src/asc/web/templates/metadata.html` | 工具栏按钮 + `fixed inset-0` Alpine modal |
| `src/asc/web/locales/{zh,en}.json` | 弹窗文案；不改 CLI `i18n.py` |

接口放在现有 `src/asc/web/routes_api.py`（与 `/api/metadata/check` 同组），用 `sync def`，避免 ASC 调用堵住事件循环。不新增 listing 领域模型，不改 `_upload_metadata_core`。

`CSV_LOCALE_TO_ASC` / `SCREENSHOT_FOLDER_TO_LOCALE` **保持不动**。它们是 CSV/截图目录简写映射，不是本弹窗的目录。

### 3.2 静态目录格式

文件为 **JSON 数组**（不是 `{ "locales": [...] }` 包装）。实现时用 `importlib.resources.files("asc").joinpath("data/asc_locales.json")` 读取，随 wheel 发布（JSON 放在 `src/asc/data/` 下即可，不必再加 `asc.data` 包）。

```json
[
  {
    "code": "zh-Hans",
    "name_en": "Chinese (Simplified)",
    "name_zh": "简体中文"
  }
]
```

校验（`list_locales()` 加载时执行，失败则抛出目录错误，由 API 变成 500）：

- 根必须是 list
- 每条必须是 object，且 `code` / `name_en` / `name_zh` 均为非空字符串（strip 后仍非空）
- `code` 全局唯一；重复则视为损坏
- 忽略未知字段
- v1 必须包含 `en-US`、`zh-Hans`、`zh-Hant`、`ja`（完整 50 条见附录）

`code` 写入 JSON 时即为 ASC API 使用的短码，加载后不再做 `normalize_locale_code`。

### 3.3 API 契约

`GET /api/metadata/locales`

无 query。Profile 只来自 cookie `asc_profile`。不读 CSV 路径，不要求工作台已加载预览。

成功（HTTP 200）：

```json
{
  "locales": [
    {
      "code": "zh-Hans",
      "name_en": "Chinese (Simplified)",
      "name_zh": "简体中文",
      "present": true
    }
  ],
  "presenceAvailable": true
}
```

- `locales`：目录全量，每条都有 `present: bool`
- 服务端不对搜索词过滤；过滤只在前端（及 `filter_locales` 供单测对齐）
- 服务端返回顺序不作为 UI 约定；UI 一律按 `code` 的 Unicode 码点升序排列（Python `sorted(..., key=lambda x: x["code"])`）

目录不可用（HTTP 500）：

```json
{ "error": "语言码目录不可用" }
```

`error` 为当前请求语言下 `t("metadata.locales_catalog_unavailable")` 的解析结果（英文 UI 则为 `Locale catalog is unavailable`）。禁止用空 `locales: []` 冒充「没有语言」。

### 3.4 已有标记规则

仅当同时满足时 `presenceAvailable: true`：

1. cookie 中有 profile
2. `Config` + `make_api_from_config` 成功
3. **先**调用 `api.get_editable_version(app_id)` 且返回非空版本
4. 再取该版本的 version localizations（可复用 `_get_available_locales`，此时空 list 只表示「版本上还没有语言」，不是「没有版本」）

`_get_available_locales` 在没有可编辑版本时也返回 `[]`，因此 handler **必须先看 version 是否存在**，不能单凭空 list 判断 `presenceAvailable`。版本已确认存在后，可用该 `version["id"]` 调 `get_version_localizations`，或再调 `_get_available_locales`（可接受多一次 `get_editable_version`）。拉取 localization 列表失败时按 ASC 失败降级，**不要** 500。

然后：将 localization 的 `locale` 做成集合，目录里 `code` **字符串全等**则为 `present: true`。ASC 返回但不在目录中的 code **丢弃**（不额外插行）。目录有、版本没有的为 `present: false`。返回给客户端的 `code` / 名称使用校验时 strip 后的值。

可编辑版本存在但 localizations 为空：`presenceAvailable: true`，全部 `present: false`。

下列情况一律 **HTTP 200 + 全量目录 + 全部 present:false + presenceAvailable:false**（弹窗必须仍能打开）：

- 无 profile / 无凭证 / 配置不完整
- Guard 拒绝（含 `GuardViolationError` / 409 类冲突）——查阅目录不走「拦截任务」语义
- ASC 超时、连接错误、401/403、其它 API 异常
- 没有可编辑版本（工具**从不创建** App Store 版本）

Presence 拉取失败不得掩盖目录本身；只有 `list_locales()` 失败才 500。

---

## 4. UI

复用 What’s New 编辑弹窗与 `#filebrowser-modal` 的模式：`fixed inset-0`、半透明遮罩、`z-50`、点遮罩关闭。截图 lightbox 仍为 `z-[60]`，本弹窗不与之叠用。

### 4.1 入口

按钮放在工作台顶栏 `listing-wb-bar` 右侧（与「加载预览」/「加载 Diff」同组），**本地 / Diff 两个 tab 都显示**。

- 不依赖 CSV 已加载、不依赖 Diff 已加载、不依赖未保存状态
- 未选 App 时按钮仍可点（打开后无「已有」标记）
- 文案：中文「语言码」/ 英文 `Locale codes`

### 4.2 弹窗结构

1. 标题：`App Store Connect 语言码`
2. 关闭按钮；`Esc` 关闭（`@keydown.escape.window`，与 lightbox 一致）
3. 可选「刷新」：强制重新请求接口（含 ASC）；**不**清空搜索框
4. 若 `presenceAvailable === false` 且目录已成功加载：顶部一句弱提示「无法标记当前版本已有语言」（非阻断，不改列表）
5. 搜索框：打开时 autofocus；占位符为 `metadata.locales_search`
6. 结果列表：每行 `code`（等宽）+ 当前 UI 语言对应的显示名（`zh` → `name_zh`，`en` → `name_en`）+ 若 `present` 则徽章「已有」
7. 「已有」只是徽章，**不是**单独 tab / 筛选器；排序始终按 `code`，不把已有项置顶
8. 底部一句说明：点击一行复制语言码，不会改动 CSV 或上传范围

加载中：列表区显示 `common.loading`。  
目录 500：列表区只显示「语言码目录不可用」+ 可点刷新；**不**渲染空表。  
无匹配：显示「无匹配语言码」；已加载的 `locales` 数组仍保留在内存。

### 4.3 过滤（客户端）

对 `code`、`name_zh`、`name_en` 做**不区分大小写的子串包含**。算法：

1. `q = query.strip()`；`q` 为空则全部通过
2. 不区分大小写：Python 用 `str.casefold()`；JS 用 `String.prototype.toLowerCase()`。v1 可搜索字符串只有 ASCII 短码与中英文名称，两种折叠对约定用例结果相同。
3. 任一字段包含 `q` 即匹配
4. 匹配结果再按 `code` 升序

约定用例：`hans` 命中 `zh-Hans`；`简体` 命中简体中文；`chinese` 命中 `name_en` 含 Chinese 的条目（至少 `zh-Hans` 与 `zh-Hant`）。

为避免没有 JS 单测框架时规则漂移：`locales_catalog.filter_locales(query, items)` 实现同一算法，pytest 测它；Alpine 按本节规则手写等价逻辑（在模板中对这三字段做包含匹配）。HTTP API **不**接受 `q` 参数。

### 4.4 复制

点击整行即复制（不另做独立复制按钮）。

1. 写入剪贴板的内容必须是该行 `code` 原样（无前后空白、不是 `简体中文(zh-Hans)`）
2. 优先 `navigator.clipboard.writeText`；失败则临时 textarea + `document.execCommand('copy')`
3. 成功：该行短暂显示「已复制」（约 2 秒后恢复），**不关闭弹窗**，方便连续查
4. 仍失败：该行内联「复制失败，请手动选择」（用户可划选 `code`）
5. 不改 hidden `locales_json` / `fields_by_locale_json` / `screenshot_scopes_json`，不改勾选，不写 CSV，不调用 listing save / metadata run

### 4.5 缓存

- 缓存在 `#metadata-page-state` 的 Alpine 内存（例如 `localeCatalog: { loaded, loading, error, locales, presenceAvailable }`）
- **不**写入 localStorage
- 再次打开：已 `loaded` 则直接显示，**不**打 ASC
- 点「刷新」才重新 GET
- 侧栏切换 App 会 `location.reload()`，内存缓存自然丢弃；新 profile 的首次打开再拉一次

---

## 5. 数据流（逐步）

1. 用户点「语言码」→ `open = true` → 若未 loaded 且未 loading 则 fetch
2. `GET /api/metadata/locales` 带上现有 cookie（`asc_profile` / `asc_lang`）
3. 服务端 `list_locales()` 读静态文件
4. 尝试 Config → API → 可编辑版本 → `_get_available_locales`；成功则打标
5. 任一步 ASC/凭证/Guard/无版本失败：目录仍返回，弱横幅
6. 前端过滤 + 排序 + 渲染
7. 点击行 → 复制 `code` → 「已复制」

---

## 6. 错误处理

| 场景 | 行为 |
|------|------|
| JSON 缺失、非 JSON、根不是数组、缺字段、空字符串、重复 `code` | HTTP 500；弹窗「语言码目录不可用」，不是空列表 |
| 无 App / 无凭证 / 配置缺 key | 200 + 目录 + `presenceAvailable: false` |
| Guard 冲突 | 同上（不 409） |
| ASC 超时 / 401 / 403 / 其它网络或 API 错 | 同上 |
| 无编辑中版本 | 同上（不创建版本） |
| 有版本但 0 条 localization | 200 + `presenceAvailable: true` + 全 `present: false` |
| 剪贴板失败 | 行内「复制失败，请手动选择」 |
| 搜索无结果 | 「无匹配语言码」；内存目录保留 |
| 重复打开 | 复用已加载数据 |
| fetch 网络失败（浏览器侧） | 弹窗错误态，可刷新；不假装已加载 |

用户可见字符串全部走 Web i18n，禁止在 Alpine 里新写死中英文（注入的 `window.t` / `__I18N`）。

### 6.1 i18n 键（`zh.json` / `en.json` 成对）

| Key | zh | en |
|-----|----|----|
| `metadata.locales_btn` | 语言码 | Locale codes |
| `metadata.locales_title` | App Store Connect 语言码 | App Store Connect locale codes |
| `metadata.locales_search` | 搜索语言码或名称 | Search codes or names |
| `metadata.locales_copied` | 已复制 | Copied |
| `metadata.locales_copy_failed` | 复制失败，请手动选择 | Copy failed. Select the code manually. |
| `metadata.locales_empty` | 无匹配语言码 | No matching locale codes |
| `metadata.locales_catalog_unavailable` | 语言码目录不可用 | Locale catalog is unavailable |
| `metadata.locales_presence_unavailable` | 无法标记当前版本已有语言 | Could not mark locales already on this version |
| `metadata.locales_present` | 已有 | On version |
| `metadata.locales_refresh` | 刷新 | Refresh |
| `metadata.locales_hint` | 点击一行复制语言码，不会改动 CSV 或上传范围 | Click a row to copy the locale code. This does not change the CSV or upload selection. |
| `metadata.locales_close` | 关闭 | Close |

---

## 7. 非目标（本期不做）

- 向 CSV 插入语言行，或改 locale 单元格格式
- 改变上传勾选 / `locales_json` / `fields_by_locale_json` / `screenshot_scopes_json`
- 在 App Store Connect 创建 localization 或创建版本
- CLI 语言码选择器或 CLI i18n 新条目
- 修改 `_upload_metadata_core` 或 listing 保存/拉取行为
- 把 `CSV_LOCALE_TO_ASC` 扩成全量目录
- 在 `/urls`、What’s New、IAP 页复用该弹窗
- 按「已有 / 未有」分 tab
- 复制 `DisplayName(code)` 或其它 CSV 友好格式
- 运行时向 Apple 拉官方 enum
- 真浏览器 E2E（仓库现有 web 测试是 TestClient + HTML 断言，无 Playwright/Selenium 套件）

本期一次实现即可，不按 P0–P4 拆交付。

---

## 8. 测试要点

默认 mock，不打真实 ASC。真网测试仅当 `ASC_TEST_LIVE=1`（与 `tests/test_api.py` 相同约定）；**本功能测试不启用 live**。

### 8.1 目录模块（`tests/test_locales_catalog.py`）

- `list_locales()` 能加载；条数等于附录的 50
- 每条非空 `code` / `name_en` / `name_zh`；`code` 唯一
- 含 `en-US`、`zh-Hans`、`zh-Hant`、`ja`
- 损坏文件（缺字段 / 重复 code / 非数组）抛错，不返回部分列表
- `filter_locales`：空查询返回全部；`hans` / `简体` / `chinese` 按第 4.3 节命中；大小写不敏感

### 8.2 API（`tests/test_web_metadata_locales.py`）

与 `test_web_listing.py` 一样：TestClient、`enforce_config_guard` mock、cookie `asc_profile`。

- ASC + 可编辑版本 + `_get_available_locales` 含 `zh-Hans`：该条 `present: true`，未出现的为 `false`，`presenceAvailable: true`，HTTP 200
- 无 cookie / `make_api_from_config` 失败 / `get_editable_version` 返回 `None` / ASC 抛错 / Guard 抛错：200、目录完整、全部 `present: false`、`presenceAvailable: false`
- mock `list_locales` 抛目录错误：500，body 含目录不可用文案
- 响应**不得**改变 CSV 文件内容

### 8.3 上传回归

现有 `tests/test_web_listing.py` 中 `/api/metadata/run` 与 listing 保存/拉取用例必须继续通过。本功能不修改那些 handler。

### 8.4 前端（现有 web 风格：GET `/metadata` 断言 HTML）

仓库没有独立 JS 运行器。断言页面包含：

- 按钮与 `GET /api/metadata/locales`（或调用它的函数名）
- modal 的 `fixed inset-0`、搜索框、刷新、复制路径（`clipboard` / `execCommand`）
- 上述 i18n key
- **没有**在复制 handler 里写 `locales-json-input` 或调用 listing save

不写 Playwright/Selenium。过滤行为由 `filter_locales` 单测覆盖。

---

## 9. 与现有代码的关键衔接点

| 现有 | 用法 |
|------|------|
| `src/asc/web/templates/metadata.html` | 顶栏按钮 + Alpine 状态 + modal |
| `whats_new.html` 编辑 modal / `#filebrowser-modal` | 遮罩、居中、`z-50`、点遮罩关闭 |
| `src/asc/web/routes_api.py` `_get_available_locales` | 仅用于 `present`；不是搜索词表 |
| cookie `asc_profile` | 与 `POST /api/metadata/check` 同一凭证上下文 |
| `src/asc/web/locales/{zh,en}.json` + `window.t` | 弹窗文案 |
| `importlib.resources`（如 `asc.templates`） | 读包内 JSON |
| `tests/test_web_listing.py` | HTML 断言风格参考；run/save 回归 |

---

## 10. 附录：v1 目录（50）

来源：Apple「Managing metadata in your app by using locale shortcodes」以及 2026-03 新增 11 种语言后的 50 项快照。`name_en` 与 Apple 短码表一致；`name_zh` 为仓库内展示名。实现必须写入这 50 条，不多不少（相对本表）。

| code | name_en | name_zh |
|------|---------|---------|
| ar-SA | Arabic | 阿拉伯语 |
| bn-BD | Bengali | 孟加拉语 |
| ca | Catalan | 加泰罗尼亚语 |
| cs | Czech | 捷克语 |
| da | Danish | 丹麦语 |
| de-DE | German | 德语 |
| el | Greek | 希腊语 |
| en-AU | English (Australia) | 英语（澳大利亚） |
| en-CA | English (Canada) | 英语（加拿大） |
| en-GB | English (U.K.) | 英语（英国） |
| en-US | English (U.S.) | 英语（美国） |
| es-ES | Spanish (Spain) | 西班牙语（西班牙） |
| es-MX | Spanish (Mexico) | 西班牙语（墨西哥） |
| fi | Finnish | 芬兰语 |
| fr-CA | French (Canada) | 法语（加拿大） |
| fr-FR | French | 法语 |
| gu-IN | Gujarati | 古吉拉特语 |
| he | Hebrew | 希伯来语 |
| hi | Hindi | 印地语 |
| hr | Croatian | 克罗地亚语 |
| hu | Hungarian | 匈牙利语 |
| id | Indonesian | 印度尼西亚语 |
| it | Italian | 意大利语 |
| ja | Japanese | 日语 |
| kn-IN | Kannada | 卡纳达语 |
| ko | Korean | 韩语 |
| ml-IN | Malayalam | 马拉雅拉姆语 |
| mr-IN | Marathi | 马拉地语 |
| ms | Malay | 马来语 |
| nl-NL | Dutch | 荷兰语 |
| no | Norwegian | 挪威语 |
| or-IN | Oriya | 奥里亚语 |
| pa-IN | Punjabi | 旁遮普语 |
| pl | Polish | 波兰语 |
| pt-BR | Portuguese (Brazil) | 葡萄牙语（巴西） |
| pt-PT | Portuguese (Portugal) | 葡萄牙语（葡萄牙） |
| ro | Romanian | 罗马尼亚语 |
| ru | Russian | 俄语 |
| sk | Slovak | 斯洛伐克语 |
| sl-SI | Slovenian | 斯洛文尼亚语 |
| sv | Swedish | 瑞典语 |
| ta-IN | Tamil | 泰米尔语 |
| te-IN | Telugu | 泰卢固语 |
| th | Thai | 泰语 |
| tr | Turkish | 土耳其语 |
| uk | Ukrainian | 乌克兰语 |
| ur-PK | Urdu | 乌尔都语 |
| vi | Vietnamese | 越南语 |
| zh-Hans | Chinese (Simplified) | 简体中文 |
| zh-Hant | Chinese (Traditional) | 繁体中文 |

不包含 `zh-HK`（不在该短码表中）。日后 Apple 增删语言：只改 JSON + 本附录，不改弹窗行为。
