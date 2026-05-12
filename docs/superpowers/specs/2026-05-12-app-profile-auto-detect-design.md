# App Profile 自动检测设计

## 背景

用户在不传入 `--app` 参数运行命令时（如 `asc upload`），如果项目根目录存在 `AppStore/Config/.env` 等本地配置文件，应该自动检测并将其与已有 app profile 一并列出让用户选择，提升使用体验。

## 核心设计

### 1. 检测条件

| 文件/目录 | 是否必填 | 说明 |
|-----------|---------|------|
| `AppStore/Config/.env` | **必填** | 凭证配置（ISSUER_ID, KEY_ID, KEY_FILE, APP_ID） |
| `AppStore/data/screenshots` | 可选 | 截图目录 |
| `AppStore/data/appstore_info.csv` | 可选 | 元数据 CSV |
| `AppStore/data/iap_packages.json` | 可选 | IAP 配置 |

**检测位置**：当前工作目录或 `--path` 指定目录。

### 2. 过滤逻辑：已有 profile 不重复列出

通过比对 `.env` 中的 `ISSUER_ID`、`KEY_ID`、`APP_ID` 与已有 profile 的凭证是否完全一致，判断该本地配置是否已被导入过。若已导入，则不列为本地选项。

```python
def _is_local_config_imported(env_creds: dict, existing_profiles: list[dict]) -> bool:
    """检查 env 中的凭证是否已对应某个已导入的 profile"""
    for profile in existing_profiles:
        if (profile["issuer_id"] == env_creds["issuer_id"]
                and profile["key_id"] == env_creds["key_id"]
                and profile["app_id"] == env_creds["app_id"]):
            return True
    return False
```

### 3. Profile 选择列表格式

当用户运行命令未指定 `--app` 时，交互式展示：

```
$ asc upload
⚠️  未指定 --app，请选择配置：

  1. profile1 (默认)
  2. profile2
  3. MyApp (local)
     AppStore/Config/.env ✓
     AppStore/data/screenshots ✓
     AppStore/data/appstore_info.csv ✓
     AppStore/data/iap_packages.json -

输入编号 (1-3):
```

- 已导入的 profile 正常列出
- 本地未导入的配置显示为 `{项目目录名} (local)` 格式，附加文件存在状态

### 4. 选择本地配置后的处理

当用户选择 `(local)` 选项时：

```
✅ 检测到 AppStore/ 目录配置

  Issuer ID:  xxx-xxx
  Key ID:     XXXXXXXXXX
  App ID:     0000000000
  .env:       AppStore/Config/.env ✓
  screenshots: AppStore/data/screenshots ✓
  CSV:        AppStore/data/appstore_info.csv ✓

  1. 仅本次使用（不保存 profile）
  2. 导入为新的 app profile
  3. 取消

输入编号 (1-3):
```

| 选项 | 行为 |
|------|------|
| 1. 仅本次使用 | 临时构建 Config 对象，运行完命令后配置不持久化 |
| 2. 导入为新 profile | 调用 `cmd_app_import` 逻辑，创建全局 profile（命名 `MyApp` 或 `MyApp-1` 等避免冲突） |
| 3. 取消 | 中断命令执行 |

### 5. 错误处理

- **非交互式环境 + 无 `--app`**：报错退出
  ```
  ❌ 检测到非交互式环境，请使用 --app 指定 App 配置，或设置 ASC_APP 环境变量。
  ```

- **本地配置不完整**（.env 缺少必填字段）：不列为选项，或列出时标记警告

- **无任何配置可用**：报错退出
  ```
  ❌ 未检测到任何 App 配置。
  请先运行 'asc app add <name>' 添加配置，或在项目根目录运行 'asc init'。
  ```

## 实现步骤

1. 在 `utils.py` 新增 `detect_local_app_config()` 检测项目本地配置
2. 新增 `_is_local_config_imported()` 判断是否已导入
3. 新增 `prompt_app_selection()` 列出 profiles + 本地配置供选择
4. 新增 `prompt_local_config_usage()` 处理用户选择本地配置后的交互
5. 在 `Config` 类新增方法支撑上述逻辑
6. 在 `i18n.py` 添加新的翻译字符串
7. 修改各命令入口函数，调用统一的 profile 解析逻辑
8. 添加单元测试

## 影响的命令范围

| 命令 | 状态 |
|------|------|
| `upload` | ✅ |
| `metadata` | ✅ |
| `keywords` | ✅ |
| `screenshots` | ✅ |
| `iap` | ✅ |
| `whats-new` | ✅ |
| `check` | ✅ |
| `build` | ✅ |
| `deploy` | ✅ |
| `release` | ✅ |
| `support-url` / `marketing-url` / `privacy-policy-url` | ✅ |
| `set-support-url` / `set-marketing-url` / `set-privacy-policy-url` | ✅ |
