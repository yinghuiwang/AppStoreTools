# App Store Connect 上传工具

[English](README.md) | [使用教程](docs/tutorials/README.zh-CN.md)

`asc` 是一个面向日常 App Store Connect 发布工作的 Python 3.9+ CLI。你可以通过终端或本地 Web UI 管理多个 App 的多语言商店内容、IAP、Xcode 构建与发布流程。

## 主要能力

- 上传多语言元数据、关键词、商店 URL 和截图
- 从 JSON 创建或更新 IAP 与自动续期订阅
- 补传缺失的 IAP 和订阅审核截图
- 更新 What's New，并可使用 LLM 自动翻译
- 构建 Xcode 项目、导出 `.ipa`，并上传到 App Store Connect 供 TestFlight 或 App Store 分发
- 使用项目默认配置管理多个 App Profile
- 通过本地 Web UI 执行常用流程，保留任务历史并发送 Webhook 通知
- 在修改远端状态前，通过机器、网络和凭证绑定执行 Guard 检查

## 使用要求

- Python 3.9 或更高版本
- 具有 **App Manager** 或更高权限的 App Store Connect API Key
- API Key 的 Issuer ID、Key ID、`.p8` 私钥，以及 App 的数字 Apple ID
- 执行 `build`、`deploy` 和 `release` 时，需要安装 macOS 与 Xcode 命令行工具

元数据、截图、IAP 和 Web UI 工作流可以在 Linux 与 Windows 上运行。Apple 只允许每个 `.p8` 私钥下载一次，请妥善保管。

## 快速开始

### 1. 安装 `asc`

推荐从 PyPI 安装已发布的包：

```bash
python -m pip install asc-appstore-tools
```

macOS / Linux 也可用仓库安装脚本（默认 PyPI，失败再回退 GitHub；`--ref` 指定分支）：

```bash
curl -fL --retry 5 --connect-timeout 20 \
  -o /tmp/asc-install.sh \
  https://raw.githubusercontent.com/yinghuiwang/AppStoreTools/main/install.sh
bash /tmp/asc-install.sh
```

也可以安装 PyPI 发布版本或 GitHub 最新源码：

```bash
python -m pip install asc-appstore-tools
# 或
python -m pip install git+https://github.com/yinghuiwang/AppStoreTools.git
```

### 2. 配置项目

在 Xcode 项目目录运行引导式配置。它会检查环境，并帮助创建或导入 App Profile：

```bash
cd /path/to/MyXcodeProject
asc install
```

手动配置时，可以用 `asc init` 生成 `AppStore/` 数据模板，或用 `asc app add myapp` 创建 Profile。Profile 和复制后的私钥保存在项目目录之外的 `~/.config/asc/`。

### 3. 检查并预览

先验证凭证，再预览默认元数据和截图上传，避免直接修改 App Store Connect：

```bash
asc check
asc upload --dry-run
```

使用 `asc --app myapp <command>` 可以显式选择 Profile；也可以运行 `asc app default myapp` 设置项目默认 App。

## 常用工作流

### 元数据和截图

```bash
# 通过 asc init 导入的 Profile 指向 AppStore/data/appstore_info.csv
asc metadata --dry-run

# 同一 Profile 指向 AppStore/data/screenshots/
asc screenshots --dry-run
```

CSV 列、语言目录、支持的 display type 和上传规则请参阅[元数据与截图上传](docs/tutorials/02-metadata-and-screenshots.zh-CN.md)。

### IAP 和订阅

```bash
asc iap --iap-file AppStore/data/iap_packages.json --dry-run
asc iap --iap-file AppStore/data/iap_packages.json --update-existing

# 查找缺少审核图的产品，并上传配置中的默认图片
asc iap-screenshots --iap-file AppStore/data/iap_packages.json --dry-run
```

建议从 `asc init` 在 `AppStore/data/iap_packages.json` 生成的当前模板开始；仓库源码中也有 `data/iap_packages.json` 示例。JSON 结构和更新规则请参阅 [IAP 与订阅上传](docs/tutorials/03-iap-and-subscriptions.zh-CN.md)。

### What's New 和商店 URL

```bash
asc whats-new --text "Bug fixes and performance improvements." --dry-run

# 通过 OpenAI 兼容 API，将一份源文本翻译到 App 的其他语言
asc whats-new --text "Bug fixes and performance improvements." \
  --translate --source-locale en-US --dry-run

asc set-support-url --text "https://example.com/support" --dry-run
asc set-marketing-url --text "https://example.com" --dry-run
asc set-privacy-policy-url --text "https://example.com/privacy" --dry-run
```

LLM 设置可通过 Web UI 或 `~/.config/asc/llm.toml` 管理，也支持 `OPENAI_API_KEY`。按文件维护版本说明和选择目标语言请参阅 [What's New 与商店 URL](docs/tutorials/04-whats-new-and-urls.zh-CN.md)。

### 构建和发布

```bash
asc build --dry-run
asc --app myapp deploy --ipa build/export/MyApp.ipa --dry-run
asc --app myapp release --destination testflight --dry-run
```

`asc build` 和 `asc release` 可以发现 Xcode 项目、Scheme、Bundle ID、签名证书和描述文件，并把解析结果缓存到 `.asc/config.toml`。签名和 App Store 发布选项请参阅[构建与发布](docs/tutorials/05-build-and-deploy.zh-CN.md)。

### 本地 Web UI

```bash
asc web
asc web status
asc web stop
```

生产环境执行 `asc web` 后，默认在 `http://127.0.0.1:8080` 打开 Vue 3 SPA。它覆盖主要的上传和发布工作流，将任务历史保存在 `~/.config/asc/tasks.db`，并可在设置页配置飞书、企业微信或钉钉任务完成通知。

本地开发使用双进程（不要添加 `asc web --vite`）：

```bash
asc web --foreground
cd frontend && npm run dev
```

Vite 在 `:5173` 将 `/api` 和 `/static` 代理到 FastAPI。发版前需要先执行 `npm ci && npm run build`，把 `src/asc/web/static/spa/` 打进包内。

运行 `asc --help` 查看全部命令，运行 `asc <command> --help` 查看完整选项。

## 配置

配置按以下优先级解析，由高到低为：

1. `--app`、`--csv`、`--screenshots` 等 CLI 选项
2. 项目本地 `.asc/config.toml`
3. 全局 App Profile
4. 环境变量

| 位置 | 用途 |
|---|---|
| `.asc/config.toml` | 项目默认值，包括默认 App 和构建配置 |
| `.asc/error.log` | 当前项目内运行命令时记录的详细错误 |
| `~/.config/asc/profiles/` | 可复用的 App Profile 与 App Store Connect 凭证 |
| `~/.config/asc/keys/` | 配置 Profile 时复制的私钥 |
| `~/.config/asc/llm.toml` | OpenAI 兼容翻译服务配置 |
| `~/.config/asc/webhook.toml` | Web 任务通知配置 |
| `~/.config/asc/tasks.db` | Web UI 持久化任务历史和日志 |

多 App 管理、Profile 导入、默认 App 与 CI 环境变量请参阅[多 App Profile 管理](docs/tutorials/06-multi-app-profiles.zh-CN.md)和 [CI/CD 自动化](docs/tutorials/08-ci-cd.zh-CN.md)。

## 使用教程

| # | 教程 | 内容 |
|---|---|---|
| 01 | [安装与项目初始化](docs/tutorials/01-install-and-init.zh-CN.md) | 安装、API Key、项目模板与第一个 Profile |
| 02 | [元数据与截图上传](docs/tutorials/02-metadata-and-screenshots.zh-CN.md) | CSV 内容、截图目录、校验与上传 |
| 03 | [IAP 与订阅上传](docs/tutorials/03-iap-and-subscriptions.zh-CN.md) | JSON 结构、一次性购买与订阅 |
| 04 | [What's New 与商店 URL](docs/tutorials/04-whats-new-and-urls.zh-CN.md) | 版本说明与支持、营销、隐私政策 URL |
| 05 | [构建与发布](docs/tutorials/05-build-and-deploy.zh-CN.md) | Archive、签名、IPA 导出，以及面向 TestFlight 或 App Store 分发的上传 |
| 06 | [多 App Profile 管理](docs/tutorials/06-multi-app-profiles.zh-CN.md) | Profile 管理与项目默认值 |
| 07 | [Guard 安全守卫](docs/tutorials/07-guard-security.zh-CN.md) | 机器、网络与凭证绑定 |
| 08 | [CI/CD 自动化](docs/tutorials/08-ci-cd.zh-CN.md) | 非交互式配置与 GitHub Actions |

## 本地开发

```bash
git clone https://github.com/yinghuiwang/AppStoreTools.git
cd AppStoreTools
python -m pip install -e ".[dev]"
pytest
python -m build
```

浏览器 E2E（`tests/test_web_agent_e2e.py`）需要 Playwright Chromium；未安装浏览器时会 skip，不会让 CI 硬失败：

```bash
python -m playwright install chromium
pytest tests/test_web_agent_e2e.py
```

源码位于 `src/asc/`，测试按功能对应放在 `tests/`。推送 `v*.*.*` Tag 后，`.github/workflows/publish.yml` 会负责发布。

修改 Vue UI 后，请运行 `cd frontend && npm ci && npm run build` 重建生产资源（需要 Node）。字体文件仍位于 `src/asc/web/static/`。

## 安全建议

- 不要提交 `.p8` 私钥、`.env` 文件、本地 Profile 或生成的凭证。
- 修改元数据、截图、IAP、URL、构建或发布状态前，先使用 `--dry-run`。
- 开发机器上应保持 Guard 启用；使用 `asc guard status` 检查绑定状态。
- 除非确实需要从其他机器访问，否则 Web UI 应绑定到 `127.0.0.1`。
- API Key 与 Webhook Secret 应保存在环境变量或 `~/.config/asc/` 下的配置文件中，不要写入上传数据。

## 常见问题

### `asc: command not found`

打开一个新终端，或重新加载 Shell 配置：

```bash
source ~/.zshrc
# 或
source ~/.bash_profile
```

### `asc check` 提示没有可编辑版本

请先在 App Store Connect 创建一个 App Store 版本。版本必须处于 `PREPARE_FOR_SUBMISSION` 等可编辑状态。

### Guard 检查阻止了操作

运行 `asc guard status` 查看当前绑定和冲突。解除绑定或关闭保护前，请先阅读 [Guard 安全守卫](docs/tutorials/07-guard-security.zh-CN.md)。

### 命令失败但信息不足

使用全局调试选项重新运行，例如 `asc --debug upload --dry-run`，并检查 `.asc/error.log`。
