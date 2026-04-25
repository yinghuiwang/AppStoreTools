# App Store Connect 上传工具

通过 App Store Connect API 批量上传应用元数据（名称、副标题、描述、关键词等）、截图和 IAP 包信息。

## 快速开始

### 方式一：curl 一键安装（最快）

```bash
# 下载并运行安装脚本（source 方式可让 asc 命令立即生效）
source <(curl -fsSL https://raw.githubusercontent.com/yinghuiwang/AppStoreTools/main/install.sh)

# 初始化项目
asc install

# 开始使用
asc upload
```

### 方式二：克隆仓库安装

```bash
# 1. 克隆仓库
git clone https://github.com/yinghuiwang/AppStoreTools.git
cd AppStoreTools

# 2. 运行安装脚本（自动检查环境并安装工具）
bash install.sh

# 3. 初始化项目（引导式配置凭证）
asc install

# 4. 运行
asc upload
```

### 方式三：手动安装

```bash
# 1. 从 PyPI 安装
pip install asc-appstore-tools

# 或从 GitHub 安装最新版本
pip install git+https://github.com/yinghuiwang/AppStoreTools.git

# 2. 初始化项目（引导式配置凭证 + 设默认 profile）
asc install

# 3. 运行
asc upload
```

## 目录结构

```
AppStoreTools/
├── src/asc/                        # pip 包源码
│   ├── commands/                   #   子命令实现
│   ├── api.py                      #   App Store Connect REST 客户端
│   ├── config.py                   #   配置管理
│   ├── constants.py                #   设备类型、Locale 映射
│   └── utils.py                    #   工具函数
├── data/                           # 上传数据
│   ├── appstore_info.csv           #   元数据 CSV
│   ├── iap_packages.example.json   #   IAP 配置示例
│   └── screenshots/                #   截图
│       ├── cn/                     #     中文截图
│       └── en/                     #     英文截图
├── pyproject.toml
└── README.md
```

## 前置准备

### 获取 API Key

1. 前往 [App Store Connect - API Keys](https://appstoreconnect.apple.com/access/integrations/api)
2. 点击 "+" 创建新的 API Key，权限选择 **App Manager** 或更高
3. 记录 **Issuer ID** 和 **Key ID**
4. 下载 `.p8` 私钥文件（只能下载一次）

### 获取 App ID

在 App Store Connect 中进入你的 App → 通用 → App 信息，页面 URL 中的数字即为 Apple ID。

### 添加应用配置

```bash
asc app add myapp
# 交互式填写：Issuer ID、Key ID、.p8 路径、App ID、数据路径
```

私钥文件会自动复制到 `~/.config/asc/keys/`，配置保存在 `~/.config/asc/profiles/myapp.toml`。

## CSV 格式

| 列名 | 说明 | 示例 |
|------|------|------|
| 语言 | 语言代码，格式 `显示名(locale)` | `简体中文(zh-Hans)` |
| 应用名称 | App Store 上显示的名称 | `PokeVid - AI视频生成器` |
| 副标题 | 名称下方的副标题 | `让照片变成精彩动态视频` |
| 长描述 | App Store 详情页描述 | 支持多行文本 |
| 关键子 | 搜索关键词，逗号分隔 | `视频制作,照片动画` |
| 技术支持链接 | 技术支持 URL（可选） | `https://...` |
| 营销网站 | 营销网站 URL（可选） | `https://...` |

## 截图目录

截图按语言放在 `data/screenshots/` 的子文件夹中，文件夹名自动映射到 locale：

| 文件夹 | Locale |
|--------|--------|
| `cn` | `zh-Hans` |
| `en` | `en-US` |
| `ja` | `ja` |
| `ko` | `ko` |

截图按文件名中的数字排序，设备类型从图片尺寸自动检测。

## 用法

```bash
# ── 安装与初始化 ──

# 全新机器：运行环境安装脚本（检查 Python/pip/git，安装 asc 工具）
bash install.sh

# 在项目目录中初始化（引导配置 App profile，设置默认）
asc install

# ── 构建与发布 ──

# 构建 .xcarchive + 导出 .ipa
asc build --scheme MyApp
asc build --project MyApp.xcworkspace --scheme MyApp --destination testflight

# 上传已有 .ipa 到 TestFlight
asc deploy --ipa build/export/MyApp.ipa
asc deploy --ipa MyApp.ipa --destination appstore

# 一键构建 + 发布
asc release --scheme MyApp --destination testflight
asc release --dry-run

# 完整上传（元数据 + 截图）
asc --app myapp upload

# 预览模式（不实际上传）
asc --app myapp upload --dry-run

# 仅上传元数据
asc --app myapp metadata

# 仅上传关键词
asc --app myapp keywords

# 仅上传截图
asc --app myapp screenshots

# 手动指定截图设备类型
asc --app myapp screenshots --display-type APP_IPHONE_67

# 仅上传 IAP 包（一次性）
asc --app myapp iap --iap-file data/iap_packages.json

# 上传订阅商品（默认跳过已存在）
asc --app myapp iap --iap-file data/iap_packages.json

# 强制更新已存在的订阅
asc --app myapp iap --iap-file data/iap_packages.json --update-existing

# ── 更新版本描述 (What's New) ──

# 所有语言使用同一段文字
asc --app myapp whats-new --text "修复已知问题，提升稳定性。"

# 限定只更新指定语言
asc --app myapp whats-new --text "Bug fixes." --locales en-US

# 从文件读取多语言更新描述
asc --app myapp whats-new --file data/whats_new.txt

# ── 直接设置 URL ──
asc --app myapp set-support-url --text "https://example.com/support"
asc --app myapp set-marketing-url --text "https://example.com" --locales en-US
asc --app myapp set-privacy-policy-url --text "https://example.com/privacy"

# 检查环境配置
asc --app myapp check

# 管理应用配置
asc app list
asc app default myapp   # 设置默认 profile
asc app remove myapp
```

### 构建配置（`.asc/config.toml`）

可在 `.asc/config.toml` 中保存构建默认值，避免每次重复输入：

```toml
[build]
project = "MyApp.xcworkspace"
scheme = "MyApp"
output = "build"
signing = "auto"
```

配置后最短用法：

```bash
asc release --destination testflight
```

### 设置默认 App（省略 `--app`）

```bash
# 方法一：命令行设置
asc app default myapp

# 方法二：手动创建 .asc/config.toml
```

```toml
[defaults]
default_app = "myapp"
```

设置后可省略 `--app` 参数：

```bash
asc upload
asc screenshots
asc check
```

### 更新描述文件格式 (`whats_new.txt`)

每种语言用 `locale:` 开头，多语言之间用 `---` 分隔：

```text
zh-Hans:
- 修复已知问题
- 提升视频生成速度
- 新增多款热门模版
---
en-US:
- Bug fixes
- Faster video generation
- New trending templates
```

### IAP 配置文件格式 (`iap_packages.json`)

支持两种结构：
- 顶层数组 `[...]`（仅一次性 IAP）
- 或对象 `{ "items": [...] }`（一次性 IAP）
- 或对象 `{ "items": [...], "subscriptionGroups": [...] }`（含订阅）

示例（一次性 IAP）：

```json
{
  "items": [
    {
      "productId": "com.example.app.coins.100",
      "name": "100 Coins",
      "inAppPurchaseType": "CONSUMABLE",
      "reviewNote": "Used to buy 100 coins in app.",
      "availableInAllTerritories": true,
      "localizations": {
        "zh-Hans": {
          "name": "100 金币",
          "description": "用于在应用内购买 100 金币。"
        },
        "en-US": {
          "name": "100 Coins",
          "description": "Used to buy 100 coins in app."
        }
      }
    }
  ]
}
```

### 订阅配置示例 (`iap_packages.json` 中的 `subscriptionGroups`)

```json
{
  "subscriptionGroups": [
    {
      "referenceName": "Pro Membership",
      "localizations": {
        "en-US": { "name": "Pro", "customAppName": "MyApp Pro" },
        "zh-Hans": { "name": "高级会员" }
      },
      "subscriptions": [
        {
          "productId": "com.example.pro.monthly",
          "name": "Pro Monthly",
          "subscriptionPeriod": "ONE_MONTH",
          "groupLevel": 1,
          "familySharable": false,
          "availableInAllTerritories": true,
          "localizations": {
            "en-US": { "name": "Pro Monthly", "description": "Unlock all features." },
            "zh-Hans": { "name": "高级会员（月）", "description": "解锁全部功能。" }
          },
          "price": { "baseTerritory": "USA", "baseAmount": "9.99" },
          "introductoryOffer": {
            "offerMode": "FREE_TRIAL",
            "duration": "ONE_WEEK",
            "numberOfPeriods": 1
          },
          "promotionalOffers": [
            {
              "referenceName": "Win-back 50off",
              "offerCode": "WINBACK50",
              "offerMode": "PAY_AS_YOU_GO",
              "duration": "ONE_MONTH",
              "numberOfPeriods": 3,
              "baseTerritory": "USA",
              "baseAmount": "4.99"
            }
          ],
          "review": {
            "screenshot": "data/iap_review/pro_monthly.png",
            "note": "Monthly auto-renewable subscription. Test: test@example.com / pw"
          }
        }
      ]
    }
  ]
}
```

完整示例见 `data/iap_packages.example.json`。

**字段说明（一次性 IAP）**：
- `productId`: IAP Product ID（唯一）
- `name`: IAP 内部名称（ASC 中显示）
- `inAppPurchaseType`: IAP 类型（如 `CONSUMABLE` / `NON_CONSUMABLE`）
- `reviewNote`: 审核备注
- `availableInAllTerritories`: 是否全地区可售
- `localizations`: 多语言信息（`name` / `description`）

**字段说明（订阅）**：
- `referenceName`: 订阅组名称
- `subscriptionPeriod`: 周期枚举（`ONE_WEEK` / `ONE_MONTH` / `TWO_MONTHS` / `THREE_MONTHS` / `SIX_MONTHS` / `ONE_YEAR`）
- `groupLevel`: 组内等级（同一组内必须唯一）
- `price.baseTerritory` + `baseAmount`: 基准价格（工具自动匹配 Price Point）
- `introductoryOffer`: 入门优惠（可选，`offerMode` 为 `FREE_TRIAL` / `PAY_AS_YOU_GO` / `PAY_UP_FRONT`）
- `promotionalOffers`: 促销优惠（可选，`offerCode` 同订阅内必须唯一）
- `review.screenshot` + `review.note`: 审核截图（PNG/JPG，≤5MB）和审核备注（必填）

### 支持的设备类型

| 设备类型 | 分辨率 |
|---------|--------|
| `APP_IPHONE_67` | 1290×2796 / 1320×2868 |
| `APP_IPHONE_65` | 1284×2778 / 1242×2688 |
| `APP_IPHONE_61` | 1179×2556 / 1170×2532 |
| `APP_IPHONE_58` | 1125×2436 |
| `APP_IPHONE_55` | 1242×2208 |
| `APP_IPAD_PRO_3GEN_129` | 2048×2732 |
| `APP_IPAD_PRO_3GEN_11` | 1668×2388 |

## 注意事项

- App Store Connect 中必须有一个处于 **准备提交** 状态的版本
- 上传截图会**删除**该设备类型下的已有截图后重新上传
- API Key 的 JWT Token 有效期 15 分钟，脚本会自动刷新
- 首次运行建议使用 `--dry-run` 预览确认
