# 单元测试套件设计 — AppStoreTools

日期：2026-04-23

## 概述

为所有当前未覆盖的模块补充完整单元测试。已有的 61 个测试（订阅、IAP dispatch、build、install）保持不变。新测试沿用 `conftest.py` 中已有的 `FakeAPI` 内存模拟模式。

所有 API 调用均使用 mock——无真实网络请求，无真实凭据。

## 待创建测试文件

### `tests/test_constants.py`

目标：`src/asc/constants.py`

- `normalize_locale_code`：
  - 空字符串 → 返回空
  - 两字符代码 `en` → 小写 `en`
  - `zh-Hans`、`ZH-HANS`、`zh_hans` → `zh-Hans`
  - `zh-Hant`、`ZH-HANT` → `zh-Hant`
  - `en_US`（下划线）→ `en-US`
  - `en-US` 正常输入 → `en-US`
- `DISPLAY_TYPE_BY_SIZE`：
  - 已知竖屏尺寸 → 返回正确设备类型
  - 相同尺寸横屏（宽高互换）→ 返回相同设备类型
  - 未知尺寸不在字典中

### `tests/test_utils.py`

目标：`src/asc/utils.py`

- `extract_locale`：
  - `简体中文(zh-Hans)` → `zh-Hans`
  - `英文(en-US)` → `en-US`
  - 纯代码 `en` → `en`
- `parse_csv`：
  - 解析真实 `data/appstore_info.csv`——断言 2 行、语言代码正确、应用名称字段存在
  - 带 BOM 编码的临时 CSV 正确解析
  - 缺少 `语言` 列的行被跳过
- `resolve_locale`：
  - 精确匹配 existing_locales → 直接返回
  - CSV 别名 `en` 通过 `CSV_LOCALE_TO_ASC` 映射 → `en-US`（当 `en-US` 在 existing 中）
  - 前缀匹配：`zh` → 返回匹配的 `zh-Hans`
  - 无匹配 → 返回 `CSV_LOCALE_TO_ASC` 兜底值或原始输入
- `md5_of_file`：
  - 写入已知字节到临时文件 → 断言已知 md5 十六进制摘要

### `tests/test_api.py`

目标：`src/asc/api.py`——默认使用 mock `requests.request`；可通过环境变量 `ASC_TEST_LIVE=1` 切换为真实网络请求。

Fixture：通过 `cryptography` 生成真实 EC 私钥写入临时文件，创建 `AppStoreConnectAPI` 实例。
真实网络模式下，从 `config/.env` 读取 `ISSUER_ID`、`KEY_ID`、`KEY_FILE`、`APP_ID`，跳过无凭据时的测试（`pytest.skip`）。

**Mock 模式（默认，`ASC_TEST_LIVE` 未设置）：**
- JWT token 缓存：有效期内连续调用 `.token` 两次 → 返回相同字符串；模拟时间超过有效期后 → 生成新 token
- `_request` 429 重试：第一次返回 429（含 `Retry-After: 1`），第二次 200 → 函数返回数据（mock `time.sleep`）
- `_request` 4xx → 抛出含状态码的 Exception
- `_request` 204 → 返回 `{}`
- `get_editable_version`：响应含 `PREPARE_FOR_SUBMISSION` 版本 + 其他版本 → 返回可编辑版本；全为不可编辑 → 返回第一个

**真实网络模式（`ASC_TEST_LIVE=1`）：**
- `get_app` 返回真实 App 数据（name、bundleId 非空）
- `get_editable_version` 返回版本对象或 None（不断言具体值，只验证结构）
- `get_app_infos` 返回非空列表

### `tests/test_metadata.py`

目标：`src/asc/commands/metadata.py`——使用本地 `MetaFakeAPI`。

所需方法：`get_app_infos`、`get_editable_version`、`get_app_info_localizations`、
`get_version_localizations`、`update_app_info_localization`、`create_app_info_localization`、
`update_version_localization`、`create_version_localization`。

测试用例：
- `_upload_metadata_core` dry_run：不调用任何 update/create
- 更新已有 app info localization（name + subtitle）
- locale 不存在时创建新 app info localization
- 更新已有版本 localization（description + keywords）
- `include_version_fields={"keywords"}` → 只更新 keywords，不更新 description
- `_update_version_field_core` 更新所有 locale 的 supportUrl
- `_update_version_field_core` 带 `locales` 过滤 → 只更新目标 locale
- `_update_version_field_core` locale 不存在 → 打印错误，不调用 API

### `tests/test_screenshots.py`

目标：`src/asc/commands/screenshots.py`

Fixture：通过 PIL 在指定尺寸生成临时 PNG 文件。

- `_detect_display_type`：1290×2796 图片 → `APP_IPHONE_67`；100×100 未知尺寸 → `None`
- `_get_sorted_screenshots`：文件夹含 `1.png`、`10.png`、`2.jpg` → 按数字后缀排序 `[1, 2, 10]`
- `_upload_screenshots_core` 目录不存在 → 不调用 API 直接返回
- `_upload_screenshots_core` dry_run → 不调用 API，打印预览信息
- `_upload_screenshots_core` 正常路径：创建截图集并上传文件（本地 FakeAPI）
- en-US 回退：`ja` 无对应文件夹 → 使用 `en-US` 文件夹替代

本地 FakeAPI 所需方法：`get_editable_version`、`get_version_localizations`、
`get_screenshot_sets`、`create_screenshot_set`、`get_screenshots_in_set`、
`delete_screenshot`、`reserve_screenshot`、`upload_screenshot_asset`、`commit_screenshot`、`get`。

### `tests/test_whats_new.py`

目标：`src/asc/commands/whats_new.py`——纯解析测试，无需 API。

- `_parse_whats_new_file` 多 locale 分隔符格式（`---`）：3 个 locale 正确解析
- `_parse_whats_new_file` 同行格式（`en-US: content`）：正确解析
- `_parse_whats_new_file` 同一文件混合两种格式
- `_parse_whats_new_file` 仅含 `---` 分隔符无内容 → 返回 `{}`
- `_parse_whats_new_file` 内容末尾空白被去除

### `tests/test_iap_core.py`

目标：`src/asc/commands/iap.py` 中的 `_upload_iap_core`——使用本地 `IapFakeAPI`。

所需方法：`list_in_app_purchases`、`create_in_app_purchase`、`update_in_app_purchase`、
`get_in_app_purchase_localizations`、`create_in_app_purchase_localization`、
`update_in_app_purchase_localization`。

测试用例：
- IAP 不存在时创建成功
- 已有 IAP 默认跳过（不调用 update）
- 已有 IAP 加 `update_existing=True` → 执行 update
- 创建新 IAP 并含 localizations → 创建 IAP 后依次创建每个 locale
- 已有 IAP 含 localizations 且 `update_existing=True` → 更新每个 locale
- dry_run：不调用任何 API
- 缺少 `productId` 的 item → 跳过并打印警告

## FakeAPI 策略

不在 `conftest.py` 的共享 `FakeAPI`（已覆盖订阅端点）中追加新方法，而是在每个新测试文件中定义一个仅包含所需方法的本地 fake 类。这样每个测试文件保持自包含，避免共享 fixture 膨胀。

## 测试数量目标

新增约 65–75 个测试。加上已有 61 个，总套件约 125–135 个测试，全部通过且运行时间 < 2 秒。

## 非目标

- 不测试 CLI（typer）入口——只测试核心函数
- 不为 `cmd_*` typer 入口函数单独写测试（配置/API 创建的接线逻辑已由现有测试模式覆盖）
- 真实网络测试仅限 `test_api.py`，其余所有测试文件始终使用 mock，不依赖网络或凭据
