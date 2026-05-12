# App Profile 自动检测设计

## 背景

用户在 Xcode 项目根目录执行 `asc init` 后，项目根目录会生成 `.asc/config.toml`，其中包含 `default_app` 配置。当用户运行需要 profile 的命令（如 `upload`、`screenshots`、`iap` 等）时，如果未通过 `--app` 指定 profile，应该自动检测并询问用户是否使用已配置的配置。

## 核心设计

### 1. 新增工具函数 `resolve_app_profile()`

位置：`src/asc/utils.py`

```python
def resolve_app_profile(app_name: Optional[str], config: Config) -> str:
    """解析要使用的 app profile。

    - 若 app_name 已指定：验证存在且配置完整
    - 若未指定且非交互式环境：报错退出
    - 若未指定且交互式环境：显示 profile 选择菜单
    - 若选择的 profile 配置不完整：报错退出
    """
```

### 2. Profile 选择菜单交互

- 当存在多个 profile 时，显示编号列表：
  ```
  检测到多个 App 配置，请选择要使用的：
    1) myapp
    2) myapp2
    3) myapp3
  请选择 [1]:
  ```
- 用户输入编号选择
- 仅显示配置完整的 profile（已验证）

### 3. 错误处理

- **非交互式环境 + 无 `--app`**：报错退出，提示使用 `--app` 或环境变量
  ```
  ❌ 检测到非交互式环境，请使用 --app 指定 App 配置，或设置 ASC_APP 环境变量。
  ```

- **选择的 profile 配置不完整**：报错退出，提示修复
  ```
  ❌ myapp 缺少必要的凭证信息（issuer_id, key_id, key_file）
  请先运行 'asc app edit myapp' 补充配置
  ```

- **无任何 profile 配置**：报错退出，提示添加
  ```
  ❌ 未检测到任何 App 配置。
  请先运行 'asc app add <name>' 添加配置，或在项目根目录运行 'asc init'。
  ```

### 4. 影响的命令范围

所有需要 App Store Connect API 的命令都会自动检测：

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

## 实现步骤

1. 在 `utils.py` 新增 `resolve_app_profile()` 函数
2. 新增 `list_valid_profiles()` 辅助函数（过滤出配置完整的 profile）
3. 在 `i18n.py` 添加新的翻译字符串
4. 修改各个命令的入口函数，在 `Config(app)` 之前调用 `resolve_app_profile()`
5. 添加单元测试
