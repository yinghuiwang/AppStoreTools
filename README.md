# App Store Connect 上传工具

通过 App Store Connect API 批量上传应用元数据（名称、副标题、描述、关键词等）、截图和 IAP 包信息。

## 快速开始

```bash
# 1. 配置 API 凭证
cp config/.env.example config/.env
# 编辑 config/.env 填写你的凭证，并将 .p8 私钥放入 config/ 目录

# 2. 一键运行（自动检查环境、安装依赖）
./run.sh
```

## 目录结构

```
AppStoreTools/
├── config/                         # 配置与密钥（git 忽略敏感文件）
│   ├── .env.example                #   配置模板
│   ├── .env                        #   实际配置
│   └── AuthKey_*.p8                #   API 私钥
├── data/                           # 上传数据
│   ├── appstore_info.csv           #   元数据 CSV
│   ├── iap_packages.example.json   #   IAP 配置示例
│   └── screenshots/                #   截图
│       ├── cn/                     #     中文截图
│       └── en/                     #     英文截图
├── upload_to_appstore.py           # 主程序
├── run.sh                          # 入口脚本
├── requirements.txt                # Python 依赖
├── .gitignore
└── README.md
```

## 前置准备

> 入口脚本会在未检测到 Python 3.9+ 时自动尝试安装：
> - macOS: `brew install python`
> - Linux: `apt-get` / `dnf` / `yum` / `pacman` / `zypper`
> 自动安装可能需要管理员权限；若安装失败，请手动安装 Python 3.9+ 后重试。

### 获取 API Key

1. 前往 [App Store Connect - API Keys](https://appstoreconnect.apple.com/access/integrations/api)
2. 点击 "+" 创建新的 API Key，权限选择 **App Manager** 或更高
3. 记录 **Issuer ID** 和 **Key ID**
4. 下载 `.p8` 私钥文件（只能下载一次），放入 `config/` 目录

### 获取 App ID

在 App Store Connect 中进入你的 App → 通用 → App 信息，页面 URL 中的数字即为 Apple ID。

### 配置 `config/.env`

```env
ISSUER_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
KEY_ID=XXXXXXXXXX
KEY_FILE=AuthKey_XXXXXXXXXX.p8
APP_ID=1234567890
```

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
# 完整上传（元数据 + 截图）
./run.sh

# 预览模式（不实际上传）
./run.sh --dry-run

# 仅上传元数据
./run.sh --metadata-only

# 仅上传截图
./run.sh --screenshots-only

# 手动指定截图设备类型
./run.sh --display-type APP_IPHONE_67

# 仅上传 IAP 包
./run.sh iap --iap-file data/iap_packages.json

# 完整上传（元数据 + 截图 + IAP）
./run.sh --iap-file data/iap_packages.json

# 指定自定义数据路径
./run.sh --csv /path/to/info.csv --screenshots /path/to/shots

# ── 更新版本描述 (What's New) ──

# 所有语言使用同一段文字
./run.sh --whats-new "修复已知问题，提升稳定性。"

# 限定只更新指定语言
./run.sh --whats-new "Bug fixes." --whats-new-locales en-US

# 从文件读取多语言更新描述
./run.sh --whats-new-file data/whats_new.txt
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
- 顶层数组 `[...]`
- 或对象 `{ "items": [...] }`

示例：

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

字段说明：
- `productId`: IAP Product ID（唯一）
- `name`: IAP 内部名称（ASC 中显示）
- `inAppPurchaseType`: IAP 类型（如 `CONSUMABLE` / `NON_CONSUMABLE`）
- `reviewNote`: 审核备注
- `availableInAllTerritories`: 是否全地区可售
- `localizations`: 多语言信息（`name` / `description`）

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
