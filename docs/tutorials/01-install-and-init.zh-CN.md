# 01 安装与项目初始化

**适用场景：** 第一次使用 `asc`，需要完成工具安装、API Key 配置和项目目录初始化。

---

## 前置条件

- macOS（build/deploy 命令仅支持 macOS；元数据上传在 Linux/Windows 也可用）
- Python 3.9 或更高版本
- 已在 App Store Connect 创建好 App（有 App ID）

---

## 步骤 1：安装 asc

**方式 A — curl 一键安装（推荐）**

```bash
source <(curl -fsSL https://raw.githubusercontent.com/yinghuiwang/AppStoreTools/main/install.sh)
```

安装完成后 `asc` 命令立即可用（`source` 会自动更新当前 shell 的 PATH）。

**方式 B — 克隆仓库安装**

```bash
git clone https://github.com/yinghuiwang/AppStoreTools.git
cd AppStoreTools
bash install.sh
```

**方式 C — PyPI**

```bash
pip install asc-appstore-tools
# 或安装 GitHub 最新版本
pip install git+https://github.com/yinghuiwang/AppStoreTools.git
```

验证安装：

```bash
asc --version
```

> **提示：** 如果提示 `asc: command not found`，执行 `source ~/.zshrc`（bash 用户执行 `source ~/.bash_profile`）。

---

## 步骤 2：创建 App Store Connect API Key

1. 打开 [App Store Connect → 用户和访问 → 集成 → API 密钥](https://appstoreconnect.apple.com/access/integrations/api)
2. 点击 **+** 创建新密钥，角色选择 **App Manager**（或更高权限）
3. 记录 **Issuer ID** 和 **Key ID**
4. 下载 `.p8` 私钥文件（**只能下载一次**，请妥善保存）

---

## 步骤 3：获取 App ID

在 App Store Connect 打开你的 App，URL 中的数字即为 App ID，例如：

```
https://appstoreconnect.apple.com/apps/1234567890/...
                                       ^^^^^^^^^^
                                       这就是 App ID
```

---

## 步骤 4：初始化项目目录（Xcode 项目推荐）

在你的 Xcode 项目根目录执行：

```bash
cd /path/to/MyXcodeProject
asc init
```

这会在项目下创建 `AppStore/` 目录结构：

```
AppStore/
├── Config/
│   └── .env          ← 填写凭证
└── data/
    ├── appstore_info.csv
    ├── screenshots/
    │   ├── cn/
    │   └── en-US/
    └── iap_packages.example.json
```

编辑 `AppStore/Config/.env`，填入你的凭证：

```dotenv
ISSUER_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
KEY_ID=XXXXXXXXXX
KEY_FILE=/path/to/AuthKey_XXXXXXXXXX.p8
APP_ID=1234567890
```

---

## 步骤 5：添加 App Profile

**方式 A — 从 .env 自动导入（推荐，配合 asc init 使用）**

```bash
asc app import
```

工具会读取当前目录的 `AppStore/Config/.env` 并自动创建 profile。

**方式 B — 指定路径导入**

```bash
asc app import --path /path/to/MyProject --name myapp
```

**方式 C — 交互式手动添加**

```bash
asc app add myapp
```

按提示依次输入 Issuer ID、Key ID、.p8 路径、App ID 和数据路径。

验证 profile 已创建：

```bash
asc app list
```

---

## 步骤 6：验证环境

```bash
asc --app myapp check
```

输出示例：

```
✅ 凭证有效
✅ 找到可编辑版本: 1.2.0 (PREPARE_FOR_SUBMISSION)
✅ CSV 文件存在: data/appstore_info.csv
✅ 截图目录存在: data/screenshots
```

---

## 设置默认 App（省略 --app）

如果你只有一个 App，可以设置默认值，之后所有命令都不需要 `--app`：

```bash
asc app default myapp
```

或在 `.asc/config.toml` 中手动写入：

```toml
[defaults]
default_app = "myapp"
```

---

## 常见问题

**Q: `asc: command not found`**
执行 `source ~/.zshrc` 重新加载 PATH。

**Q: `❌ Key file not found`**
检查 `.p8` 文件路径是否正确，支持 `~` 展开，例如 `~/Downloads/AuthKey_XXXXXXXXXX.p8`。

**Q: `asc check` 提示"找不到可编辑的 App Store 版本"**
在 App Store Connect 中为该 App 创建一个新版本（状态为 `PREPARE_FOR_SUBMISSION`），`asc` 不会自动创建版本。

**Q: `install.sh`、`asc install` 和 `asc init` 有什么区别？**
- `install.sh`：安装 CLI 工具本体（Python 环境 + `asc` 命令）
- `asc install`：引导式项目初始化向导，检查环境并配置 App profile
- `asc init`：在 Xcode 项目目录生成 `AppStore/` 模板目录结构（每个项目运行一次）

---

## 下一步

- [02 元数据与截图上传](02-metadata-and-screenshots.zh-CN.md) — 填写 CSV 并上传内容
- [06 多 App Profile 管理](06-multi-app-profiles.zh-CN.md) — 管理多个 App
