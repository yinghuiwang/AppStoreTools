# AppStoreTools 技术架构文档

## 概述

AppStoreTools (`asc`) 是一个用于批量上传 App Store Connect 元数据的 CLI 工具，支持元数据、截图、IAP、订阅等内容的自动化管理。

**核心特性：**
- 🔐 JWT 认证 + 安全守卫系统
- 🌍 国际化支持（中英文）
- 📦 多优先级配置系统
- 🔄 自动重试 + 速率限制处理
- 🛡️ 机器/IP/凭证三重绑定防护

---

## 系统架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                          👤 用户层                               │
│                      asc CLI 命令入口                            │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    📦 命令层 (commands/)                         │
├─────────────────────────────────────────────────────────────────┤
│  metadata.py        │ 元数据上传（名称、描述、关键词）            │
│  screenshots.py     │ 截图上传（自动检测设备类型）                │
│  iap.py             │ IAP 管理（一次性购买）                     │
│  subscriptions.py   │ 订阅管理（自动续期订阅）                    │
│  whats_new.py       │ 更新说明管理                               │
│  build.py           │ 构建/部署（xcodebuild + TestFlight）      │
│  app_config.py      │ App 配置管理（add/list/remove）           │
│  guard_cmd.py       │ 守卫命令（status/enable/disable）         │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    🔧 核心层                                     │
├─────────────────────────────────────────────────────────────────┤
│  api.py             │ AppStoreConnectAPI (JWT + REST)          │
│  config.py          │ Config 配置系统（4级优先级）               │
│  guard.py           │ Guard 安全守卫（机器/IP/凭证绑定）         │
│  utils.py           │ 工具函数（CSV解析、locale映射）            │
│  i18n.py            │ 国际化（中英文）                           │
│  constants.py       │ 常量定义（设备尺寸、地区映射）              │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│              📁 数据文件                                         │
├─────────────────────────────────────────────────────────────────┤
│  data/appstore_info.csv        │ 元数据（多语言）               │
│  data/screenshots/<locale>/    │ 截图目录                       │
│  data/iap_packages.json        │ IAP/订阅配置                   │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│              🌐 App Store Connect REST API                      │
│  api.appstoreconnect.apple.com/v1                               │
├─────────────────────────────────────────────────────────────────┤
│  /apps                          │ App 信息                       │
│  /appInfoLocalizations          │ App 本地化信息                 │
│  /appStoreVersionLocalizations  │ 版本本地化信息                 │
│  /screenshotSets                │ 截图集合                       │
│  /inAppPurchases                │ IAP 产品                       │
│  /subscriptionGroups            │ 订阅组                         │
└─────────────────────────────────────────────────────────────────┘
```

---

## 配置系统（4级优先级）

```
┌──────────────────────────────────────────────────────────────┐
│                    配置优先级 (从高到低)                       │
└──────────────────────────────────────────────────────────────┘

1️⃣  CLI 参数 (最高优先级)
    asc --app myapp --csv custom.csv --screenshots ./shots
    └─ 直接覆盖所有其他配置

2️⃣  本地项目配置
    .asc/config.toml
    ├─ [credentials]
    │  ├─ issuer_id = "..."
    │  ├─ key_id = "..."
    │  ├─ key_file = "..."
    │  └─ app_id = "..."
    ├─ [defaults]
    │  ├─ csv = "data/appstore_info.csv"
    │  ├─ screenshots = "data/screenshots"
    │  └─ default_app = "myapp"
    └─ [build]
       ├─ project = "MyApp.xcodeproj"
       └─ scheme = "MyApp"

3️⃣  全局 App 配置文件
    ~/.config/asc/profiles/<app_name>.toml
    ├─ [credentials]
    │  ├─ issuer_id = "..."
    │  ├─ key_id = "..."
    │  ├─ key_file = "..."
    │  └─ app_id = "..."
    └─ [defaults]
       ├─ csv = "data/appstore_info.csv"
       └─ screenshots = "data/screenshots"

4️⃣  环境变量 (最低优先级)
    ├─ ISSUER_ID
    ├─ KEY_ID
    ├─ KEY_FILE
    ├─ APP_ID
    ├─ ASC_LANG (zh/en)
    └─ ASC_GUARD_DISABLE (1 禁用守卫)
```

---

## 数据流：用户输入 → API 调用

```
用户输入
  │
  │  asc --app myapp upload --csv data.csv
  │
  ▼
┌─────────────────────────────────────────┐
│ CLI 层 (cli.py)                         │
│ • 解析命令行参数                         │
│ • 设置 _ASC_APP 环境变量                 │
│ • 路由到对应命令函数                     │
└────────────┬────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────┐
│ 命令处理层 (commands/metadata.py)       │
│ • 读取配置 (Config)                     │
│ • 验证守卫 (Guard.check_and_enforce)    │
│ • 解析输入数据 (CSV/JSON/图片)          │
│ • 调用 API 方法                         │
└────────────┬────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────┐
│ 配置层 (config.py)                      │
│ 优先级链:                               │
│ CLI args > 本地 toml > 全局 profiles    │
│          > 环境变量                     │
└────────────┬────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────┐
│ 守卫层 (guard.py)                       │
│ • 检查机器指纹/IP/凭证绑定               │
│ • 防止凭证滥用                          │
│ • 记录使用日志                          │
└────────────┬────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────┐
│ API 层 (api.py)                         │
│ AppStoreConnectAPI 类:                  │
│ • JWT 认证 (15分钟 token)               │
│ • HTTP 请求 (GET/POST/PATCH/DELETE)     │
│ • 速率限制处理 (429 重试)                │
│ • 错误处理                              │
└────────────┬────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────┐
│ App Store Connect REST API              │
│ api.appstoreconnect.apple.com/v1        │
└─────────────────────────────────────────┘
```

---

## 核心模块详解

### 1. API 层 (`api.py` - 720 行)

**类**: `AppStoreConnectAPI`

**核心功能**:
- JWT Token 生成（15分钟有效期，自动刷新）
- HTTP 方法封装（GET/POST/PATCH/DELETE）
- 速率限制处理（429 状态码 + Retry-After）
- 错误处理和重试机制

**主要方法**:
```python
# App 信息
get_app(app_id)
get_app_infos(app_id)
get_app_info_localizations(app_info_id)

# 版本管理
get_editable_version(app_id)
get_version_localizations(version_id)

# 截图
get_screenshot_sets(version_localization_id)
reserve_screenshot(screenshot_set_id, filename, size)
upload_screenshot_asset(upload_operations, file_path)
commit_screenshot(screenshot_id, md5)

# IAP
list_in_app_purchases(app_id)
create_in_app_purchase(app_id, product_id, name, type)
update_in_app_purchase(iap_id, attrs)

# 订阅
list_subscription_groups(app_id)
create_subscription(group_id, product_id, name, period)
find_subscription_price_point(subscription_id, territory, amount)
create_subscription_price(subscription_id, price_point_id)
```

---

### 2. 配置系统 (`config.py` - 194 行)

**类**: `Config`

**配置优先级**:
1. CLI 参数（最高）
2. 本地 `.asc/config.toml`
3. 全局 `~/.config/asc/profiles/<name>.toml`
4. 环境变量（最低）

**主要属性**:
```python
issuer_id: str          # JWT Issuer ID
key_id: str             # API Key ID
key_file: str           # 私钥文件路径
app_id: str             # App Store Connect App ID
csv_path: str           # 元数据 CSV 路径
screenshots_path: str   # 截图目录路径
build_project: str      # Xcode 项目路径
build_scheme: str       # Xcode Scheme
```

**主要方法**:
```python
list_apps()                          # 列出所有 app 配置
save_app_profile(name, config)       # 保存 app 配置
remove_app_profile(name)             # 删除 app 配置
get_app_profile(name)                # 获取 app 配置
```

---

### 3. 守卫系统 (`guard.py` - 168 行)

**类**: `Guard`

**绑定类型**:
- **机器指纹**: macOS 使用 IOPlatformUUID，其他系统使用 platform.node() + uuid.getnode()
- **IP 地址**: 从 api.ipify.org 或 ifconfig.me 获取公网 IP
- **凭证**: Key ID 绑定

**主要方法**:
```python
is_enabled()                         # 检查守卫是否启用
bind(app_name, key_id, issuer_id)    # 绑定当前环境
unbind(bind_type, current_only)      # 解除绑定
enable()                             # 启用守卫
disable()                            # 禁用守卫
check_and_enforce(app_id, ...)       # 检查并强制执行绑定
```

**存储位置**: `~/.config/asc/guard.json`

**异常类型**:
- `GuardError`: 守卫基础异常
- `GuardViolationError`: 绑定冲突异常
- `GuardConfigError`: 配置错误异常

---

### 4. 命令层 (`commands/`)

#### `metadata.py` (692 行)
- `cmd_upload()`: 上传所有内容（元数据 + 截图）
- `cmd_metadata()`: 仅上传元数据
- `cmd_keywords()`: 查看/上传关键词
- `cmd_set_support_url()`: 设置支持 URL
- `cmd_set_marketing_url()`: 设置营销 URL
- `cmd_set_privacy_policy_url()`: 设置隐私政策 URL
- `cmd_check()`: 检查元数据完整性

#### `screenshots.py` (252 行)
- `cmd_screenshots()`: 上传截图
- 自动检测设备类型（基于图片尺寸）
- 支持的设备类型：
  - iPhone 6.7" / 6.5" / 5.5"
  - iPad Pro 12.9" / 11"
  - Apple Watch

#### `iap.py` (245 行)
- `cmd_iap()`: 上传 IAP 产品
- 支持类型：
  - CONSUMABLE（消耗型）
  - NON_CONSUMABLE（非消耗型）
  - AUTO_RENEWABLE_SUBSCRIPTION（自动续期订阅）

#### `subscriptions.py` (533 行)
- `cmd_subscriptions()`: 上传订阅配置
- 支持功能：
  - 订阅组管理
  - 订阅本地化
  - 价格设置（基于 baseTerritory + baseAmount）
  - 介绍性优惠（免费试用、按优惠价付费）
  - 促销优惠
  - 审核截图

#### `whats_new.py` (190 行)
- `cmd_whats_new()`: 更新 "What's New" 字段
- 支持单语言文本或多语言文件

#### `build.py` (443 行)
- `cmd_build()`: 构建 .ipa
- `cmd_deploy()`: 部署到 TestFlight/App Store
- `cmd_release()`: 构建 + 部署一步完成

#### `app_config.py` (617 行)
- `cmd_app_add()`: 添加新 app 配置
- `cmd_app_list()`: 列出所有 app
- `cmd_app_show()`: 显示 app 详情
- `cmd_app_edit()`: 编辑 app 配置
- `cmd_app_remove()`: 删除 app 配置
- `cmd_app_default()`: 设置默认 app
- `cmd_app_import()`: 从 ASC 导入配置

#### `guard_cmd.py` (114 行)
- `cmd_guard_status()`: 查看绑定状态
- `cmd_guard_enable()`: 启用守卫
- `cmd_guard_disable()`: 禁用守卫
- `cmd_guard_reset()`: 重置守卫
- `cmd_guard_unbind()`: 解除绑定

---

## CLI 命令树

```
asc
├── --version, -v              # 显示版本
├── --app, -a <name>           # 指定 app 配置
│
├── 元数据命令
│   ├── upload                 # 上传所有内容
│   ├── metadata               # 仅上传元数据
│   ├── keywords               # 查看/上传关键词
│   ├── support-url            # 查看支持 URL
│   ├── marketing-url          # 查看营销 URL
│   ├── privacy-policy-url     # 查看隐私政策 URL
│   ├── set-support-url        # 设置支持 URL
│   ├── set-marketing-url      # 设置营销 URL
│   ├── set-privacy-policy-url # 设置隐私政策 URL
│   └── check                  # 检查元数据完整性
│
├── 内容命令
│   ├── screenshots            # 上传截图
│   ├── whats-new              # 上传更新说明
│   └── iap                    # 上传 IAP/订阅
│
├── App 配置命令
│   ├── app add <name>         # 添加新 app 配置
│   ├── app list               # 列出所有 app
│   ├── app show <name>        # 显示 app 详情
│   ├── app edit <name>        # 编辑 app 配置
│   ├── app remove <name>      # 删除 app 配置
│   ├── app default <name>     # 设置默认 app
│   └── app import <name>      # 从 ASC 导入配置
│
├── 项目初始化
│   ├── install                # 交互式项目初始化
│   └── init                   # 初始化项目结构
│
├── 构建/部署
│   ├── build                  # 构建 .ipa
│   ├── deploy                 # 部署到 TestFlight
│   └── release                # 发布到 App Store
│
└── 守卫命令
    ├── guard status           # 查看绑定状态
    ├── guard enable           # 启用守卫
    ├── guard disable          # 禁用守卫
    ├── guard reset            # 重置守卫
    └── guard unbind <type>    # 解除绑定
```

---

## 数据文件格式

### CSV 元数据格式

```csv
语言,应用名称,副标题,描述,关键词,支持网址,营销网址,隐私政策网址
简体中文(zh-Hans),我的应用,简介,完整描述,关键词1;关键词2,https://support.com,https://marketing.com,https://privacy.com
英文(en-US),My App,Subtitle,Full description,keyword1;keyword2,https://support.com,https://marketing.com,https://privacy.com
```

### IAP/订阅 JSON 格式

```json
{
  "items": [
    {
      "productId": "com.example.app.premium",
      "name": "Premium",
      "type": "CONSUMABLE"
    }
  ],
  "subscriptionGroups": [
    {
      "referenceName": "Premium Membership",
      "subscriptions": [
        {
          "productId": "com.example.app.premium.monthly",
          "subscriptionPeriod": "ONE_MONTH",
          "groupLevel": 1,
          "price": {
            "baseTerritory": "US",
            "baseAmount": "9.99"
          },
          "introductoryOffer": {
            "offerMode": "FREE_TRIAL",
            "duration": "ONE_WEEK"
          }
        }
      ]
    }
  ]
}
```

### 截图目录结构

```
data/screenshots/
├── cn/                    # 简体中文
│   ├── iphone_67_1.png   # 6.7" iPhone
│   ├── iphone_67_2.png
│   └── ipad_pro_129_1.png
├── en-US/                 # 英文
│   ├── iphone_67_1.png
│   └── ...
└── ja/                    # 日文
    └── ...
```

---

## 外部依赖

```toml
[dependencies]
typer>=0.12.0              # CLI 框架
PyJWT>=2.8.0               # JWT 认证
cryptography>=41.0.0       # 加密库
requests>=2.31.0           # HTTP 客户端
Pillow>=10.0.0             # 图片处理
python-dotenv>=1.0.0       # .env 文件支持
tomli>=2.0.0               # TOML 解析
```

**Python 版本支持**: 3.9, 3.10, 3.11, 3.12

---

## 核心工作流程

### 初始化流程

```
asc install
  ├─ 检测 Xcode 项目
  ├─ 创建 .asc/ 目录
  ├─ 生成 config.toml 模板
  ├─ 创建 data/appstore_info.csv
  ├─ 创建 data/screenshots/ 目录
  └─ 创建 data/iap_packages.json
```

### 上传流程

```
asc upload
  ├─ 读取配置 (Config)
  ├─ 验证守卫 (Guard)
  ├─ 解析 CSV 元数据
  ├─ 上传元数据到 ASC
  ├─ 上传截图到 ASC
  └─ 显示结果摘要
```

### 构建/部署流程

```
asc build
  ├─ 检测 Xcode 项目
  ├─ 执行 xcodebuild
  └─ 生成 .ipa

asc deploy
  ├─ 构建 .ipa
  ├─ 上传到 TestFlight
  └─ 等待处理

asc release
  ├─ 构建 .ipa
  ├─ 上传到 App Store
  └─ 提交审核
```

---

## 安全特性

### Guard 系统

**绑定类型**:
- **机器指纹**: macOS 使用 IOPlatformUUID，其他系统使用 platform.node() + uuid.getnode()
- **IP 地址**: 从 api.ipify.org 或 ifconfig.me 获取公网 IP
- **凭证**: Key ID 绑定

**冲突检测**:
- 同一凭证在不同机器/IP 使用时触发警告
- 防止凭证泄露和滥用

**存储位置**: `~/.config/asc/guard.json`

---

## 项目结构

```
AppStoreTools/
├── src/asc/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py                 # CLI 主应用
│   ├── api.py                 # API 客户端
│   ├── config.py              # 配置系统
│   ├── guard.py               # 安全守卫
│   ├── utils.py               # 工具函数
│   ├── i18n.py                # 国际化
│   ├── constants.py           # 常量定义
│   ├── commands/              # 命令模块
│   │   ├── metadata.py
│   │   ├── screenshots.py
│   │   ├── iap.py
│   │   ├── subscriptions.py
│   │   ├── whats_new.py
│   │   ├── build.py
│   │   ├── app_config.py
│   │   └── guard_cmd.py
│   └── templates/             # 模板文件
│       ├── iap_packages.json
│       └── iap_review/
├── data/                      # 数据文件（用户创建）
│   ├── appstore_info.csv
│   ├── screenshots/
│   └── iap_packages.json
├── .asc/                      # 本地配置（用户创建）
│   └── config.toml
├── pyproject.toml             # 项目配置
├── install.sh                 # 安装脚本
├── CLAUDE.md                  # 项目文档
├── ARCHITECTURE.md            # 架构文档（本文件）
└── README.md                  # 用户文档
```

---

## 设计原则

1. **分层架构**: CLI → 命令 → 配置 → API → ASC REST API
2. **配置优先级**: 灵活的多级配置系统，适应不同使用场景
3. **安全第一**: 内置守卫系统，防止凭证滥用
4. **国际化**: 支持中英文，易于扩展其他语言
5. **模块化**: 每个命令独立模块，易于维护和扩展
6. **错误处理**: 完善的错误处理和重试机制
7. **用户友好**: 清晰的命令结构和帮助文档

---

## 扩展指南

### 添加新命令

1. 在 `src/asc/commands/` 创建新模块
2. 定义命令函数（使用 `@app.command()` 装饰器）
3. 在 `cli.py` 中注册命令
4. 添加国际化文本到 `i18n.py`

### 添加新 API 方法

1. 在 `api.py` 的 `AppStoreConnectAPI` 类中添加方法
2. 遵循现有命名规范（get_/create_/update_/delete_）
3. 添加错误处理和重试逻辑

### 添加新配置项

1. 在 `config.py` 的 `Config` 类中添加属性
2. 更新配置文件模板
3. 更新文档

---

## 相关文档

- [README.md](README.md) - 用户使用指南
- [CLAUDE.md](CLAUDE.md) - 项目开发指南
- [App Store Connect API 文档](https://developer.apple.com/documentation/appstoreconnectapi)
