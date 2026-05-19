# App Store Connect 上传工具

[English](README.md) | [使用教程](docs/tutorials/README.zh-CN.md)

`asc` 是一个用于 App Store Connect 发布工作的 Python CLI。它可以上传多语言元数据和截图，创建或更新 IAP 与自动续期订阅，维护 What’s New 与商店 URL，构建 Xcode 项目，上传 `.ipa`，并提供本地 Web UI 处理常用流程。

## 功能概览

- 从 `data/appstore_info.csv` 上传 App 元数据
- 按语言和设备尺寸上传截图，并自动识别 display type
- 从 JSON 同步 IAP 和自动续期订阅
- 更新版本说明、技术支持 URL、营销 URL、隐私政策 URL
- 构建 Xcode Archive、导出 IPA、上传到 App Store Connect
- 支持多 App Profile 和本地默认 App
- Guard 在高风险操作前检查机器、IP、凭证绑定
- 通过 `asc web` 启动本地 Web UI

## 使用教程

每个主要工作流的分步指南：

| # | 教程 | 主题 |
|---|------|------|
| 01 | [安装与项目初始化](docs/tutorials/01-install-and-init.zh-CN.md) | 安装 `asc`、创建 API Key、初始化项目、添加 App Profile |
| 02 | [元数据与截图上传](docs/tutorials/02-metadata-and-screenshots.zh-CN.md) | 填写 CSV、命名截图文件夹、运行 `upload` / `metadata` / `screenshots` |
| 03 | [IAP 与订阅上传](docs/tutorials/03-iap-and-subscriptions.zh-CN.md) | 编写 `iap_packages.json`、上传一次性内购和订阅 |
| 04 | [What's New 与商店 URL](docs/tutorials/04-whats-new-and-urls.zh-CN.md) | 更新版本说明和支持/营销/隐私政策 URL |
| 05 | [构建与发布](docs/tutorials/05-build-and-deploy.zh-CN.md) | `asc build`、`asc deploy`、`asc release`、TestFlight 与 App Store |
| 06 | [多 App Profile 管理](docs/tutorials/06-multi-app-profiles.zh-CN.md) | 管理多个 App、设置默认 App、在项目间切换 |
| 07 | [Guard 安全守卫](docs/tutorials/07-guard-security.zh-CN.md) | 机器/IP/凭证绑定、冲突处理、CI 环境关闭守卫 |
| 08 | [CI/CD 自动化](docs/tutorials/08-ci-cd.zh-CN.md) | GitHub Actions 示例、通过环境变量注入凭证 |

## 快速开始

### 方式一：curl 一键安装

```bash
source <(curl -fsSL https://raw.githubusercontent.com/yinghuiwang/AppStoreTools/main/install.sh)
asc install
asc upload --dry-run
```

### 方式二：克隆仓库安装

```bash
git clone https://github.com/yinghuiwang/AppStoreTools.git
cd AppStoreTools
bash install.sh
asc install
asc upload --dry-run
```

### 方式三：从 PyPI 或 GitHub 安装

```bash
pip install asc-appstore-tools
# 或安装 GitHub 最新版本
pip install git+https://github.com/yinghuiwang/AppStoreTools.git

asc install
asc upload --dry-run
```

本地开发安装：

```bash
pip install -e ".[dev]"
pytest
```

## 前置准备

1. 在 [App Store Connect > 用户和访问 > 集成](https://appstoreconnect.apple.com/access/integrations/api) 创建 API Key。
2. 建议使用 **App Manager** 或更高权限。
3. 记录 **Issuer ID** 和 **Key ID**。
4. 下载 `.p8` 私钥。Apple 只允许下载一次。
5. 从 App Store Connect 复制目标 App 的数字 Apple ID。

## 项目配置

### 初始化新项目

```bash
cd /path/to/MyXcodeProject
asc init
# 填写 AppStore/Config/.env，然后：
asc app import
```

### 导入已有 AppStore/Config/.env

```bash
asc app import --path /path/to/MyProject --name myapp
```

### 交互式配置

```bash
asc app add myapp
```

私钥会复制到 `~/.config/asc/keys/`。Profile 会保存到 `~/.config/asc/profiles/`。

## 项目结构

```text
AppStoreTools/
├── src/asc/                        # Python 包源码
│   ├── commands/                   # CLI 子命令
│   ├── web/                        # 本地 Web UI
│   ├── api.py                      # App Store Connect REST 客户端
│   ├── config.py                   # 配置管理
│   └── i18n.py                     # 中英文 CLI 文案
├── data/                           # 示例上传数据
│   ├── appstore_info.csv           # 元数据 CSV
│   ├── iap_packages.example.json   # IAP/订阅示例
│   └── screenshots/                # 按语言存放截图
├── docs/tutorials/                 # 工作流教程
├── tests/                          # pytest 测试
└── pyproject.toml
```

## CSV 格式

`data/appstore_info.csv` 需要包含这些列：

| 列名 | 含义 |
|---|---|
| `语言` | `显示名称(code)` 格式的语言，例如 `简体中文(zh-Hans)` |
| `应用名称` | App 名称 |
| `副标题` | 副标题 |
| `长描述` | App 描述 |
| `关键子` | 关键词，英文逗号分隔 |
| `技术支持链接` | 技术支持 URL，可选 |
| `营销网站` | 营销 URL，可选 |

## 截图目录

截图从 `data/screenshots/<folder>/` 读取：

| 文件夹 | Locale |
|---|---|
| `cn` | `zh-Hans` |
| `en` | `en-US` |
| `ja` | `ja` |
| `ko` | `ko` |

截图按文件名中的数字顺序上传。设备类型会根据图片尺寸自动识别；也可以用 `--display-type` 只上传指定设备类型。

## 命令速查

```bash
# 帮助 / 版本
asc --help
asc -h
asc --version

# 引导式配置和项目模板
asc install
asc init
asc init --path /path/to/MyApp

# App Profile
asc app add myapp
asc app import
asc app import --path /path/to/project --name myapp
asc app list
asc app default myapp
asc app show myapp
asc app edit myapp
asc app remove myapp

# 元数据和截图
asc --app myapp upload
asc --app myapp upload --dry-run
asc --app myapp metadata
asc --app myapp keywords
asc --app myapp screenshots
asc --app myapp screenshots --display-type APP_IPHONE_67
asc --app myapp check

# IAP 和订阅
asc --app myapp iap --iap-file data/iap_packages.json
asc --app myapp iap --iap-file data/iap_packages.json --update-existing

# What’s New
asc --app myapp whats-new --text "修复已知问题，提升稳定性。"
asc --app myapp whats-new --text "Bug fixes." --locales en-US
asc --app myapp whats-new --file data/whats_new.txt

# 商店 URL
asc --app myapp set-support-url --text "https://example.com/support"
asc --app myapp set-marketing-url --text "https://example.com" --locales en-US
asc --app myapp set-privacy-policy-url --text "https://example.com/privacy"
asc --app myapp support-url
asc --app myapp marketing-url
asc --app myapp privacy-policy-url

# 构建和发布
asc build
asc build --project MyApp.xcworkspace --scheme MyApp
asc build --signing manual --profile path/to/profile.mobileprovision --certificate "Apple Distribution: ACME"
asc build --no-interactive --dry-run
asc --app myapp deploy --ipa build/export/MyApp.ipa
asc --app myapp release --destination testflight
asc --app myapp release --destination appstore --reuse-archive

# 本地 Web UI
asc web
asc web --port 9090
asc web --host 0.0.0.0 --no-open

# Guard
asc guard status
asc guard enable
asc guard disable
asc guard unbind --current
asc guard unbind --credential <KEY_ID>
asc guard reset

# 维护
asc update
asc update --version 0.1.12
asc update --branch main
asc uninstall
```

## 构建默认配置

构建配置可以保存在本地 `.asc/config.toml`：

```toml
[build]
project = "MyApp.xcworkspace"
scheme = "MyApp"
bundle_id = "com.example.myapp"
output = "build"
signing = "auto"
certificate = "Apple Distribution: Example Inc."
profile = "/path/to/profile.mobileprovision"
destination = "testflight"
```

`asc build` 和 `asc release` 可以自动检测项目、Scheme、Bundle ID、签名证书和描述文件，并把解析结果缓存到 `.asc/config.toml` 供后续运行复用。

## 默认 App Profile

设置默认 Profile 后可以省略 `--app`：

```bash
asc app default myapp
```

也可以手动写入配置：

```toml
[defaults]
default_app = "myapp"
```

之后可以直接运行：

```bash
asc upload
asc screenshots
asc check
```

## 配置与安全

- 全局 Profile 位于 `~/.config/asc/profiles/`。
- 私钥会复制到 `~/.config/asc/keys/`。
- 项目本地配置位于 `.asc/config.toml`。
- 不要提交真实 `.p8` 私钥、`.env` 文件、本地 Profile 或生成的凭证。
- 修改元数据、截图、IAP、订阅或发布状态前，建议先运行 `--dry-run`。
- 构建和发布需要 macOS 与 Xcode 命令行工具；元数据相关命令可在 Linux 或 Windows 上运行。

## 常见问题

### `asc: command not found`

```bash
source ~/.zshrc
# 或
source ~/.bash_profile
```

### `asc check` 提示没有可编辑版本

请先在 App Store Connect 创建一个 App Store 版本。版本状态需要是 `PREPARE_FOR_SUBMISSION` 等可编辑状态。

### `install.sh`、`asc install` 与 `asc init` 的区别

- `install.sh`：安装 CLI 工具本体，包括 Python 环境和 `asc` 命令。
- `asc install`：引导式项目初始化，检查环境并配置 App Profile。
- `asc init`：在 Xcode 项目目录生成 `AppStore/` 模板目录结构，每个项目通常只需要运行一次。
