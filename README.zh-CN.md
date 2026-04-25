# App Store Connect 上传工具

[English](README.md)

`asc` 是一个面向 App Store Connect 的发布 CLI，覆盖从素材上传到发布的完整流程：上传元数据/截图/IAP 与订阅、管理多语言 What’s New 与商店 URL、以及构建并分发 `.ipa` 到 TestFlight 或 App Store。

## 快速开始

### 方式一：curl 一键安装（最快）

```bash
source <(curl -fsSL https://raw.githubusercontent.com/yinghuiwang/AppStoreTools/main/install.sh)
asc install
asc upload
```

### 方式二：克隆仓库安装

```bash
git clone https://github.com/yinghuiwang/AppStoreTools.git
cd AppStoreTools
bash install.sh
asc install
asc upload
```

### 方式三：PyPI 安装

```bash
pip install asc-appstore-tools
# 或安装 GitHub 最新版本
pip install git+https://github.com/yinghuiwang/AppStoreTools.git

asc install
asc upload
```

## 前置准备

1. 在 App Store Connect 创建 API Key（建议 App Manager 权限）
2. 记录 `Issuer ID`、`Key ID` 并下载 `.p8` 私钥
3. 通过 `asc app add myapp` 配置 profile

```bash
asc app add myapp
```

## 常用命令

```bash
# 完整上传（元数据 + 截图）
asc --app myapp upload

# 预览模式
asc --app myapp upload --dry-run

# 仅上传元数据 / 关键词 / 截图
asc --app myapp metadata
asc --app myapp keywords
asc --app myapp screenshots

# 上传 IAP / 订阅
asc --app myapp iap --iap-file data/iap_packages.json
asc --app myapp iap --iap-file data/iap_packages.json --update-existing

# 更新 What’s New
asc --app myapp whats-new --text "修复已知问题，提升稳定性。"
asc --app myapp whats-new --file data/whats_new.txt

# URL 配置
asc --app myapp set-support-url --text "https://example.com/support"
asc --app myapp set-marketing-url --text "https://example.com" --locales en-US
asc --app myapp set-privacy-policy-url --text "https://example.com/privacy"

# 校验
asc --app myapp check
```

## Profile 管理

```bash
asc app list
asc app default myapp
asc app show myapp
asc app edit myapp
asc app remove myapp
```

## Guard 命令

```bash
asc guard status
asc guard enable
asc guard disable
asc guard unbind --current
asc guard unbind --credential <KEY_ID>
asc guard reset
```

## 构建与发布

```bash
asc build --scheme MyApp
asc deploy --ipa build/export/MyApp.ipa
asc release --scheme MyApp --destination testflight
```

在 `.asc/config.toml` 中可保存默认构建配置：

```toml
[build]
project = "MyApp.xcworkspace"
scheme = "MyApp"
output = "build"
signing = "auto"
```

## 默认 App（省略 `--app`）

```bash
asc app default myapp
```

或手动写入：

```toml
[defaults]
default_app = "myapp"
```

## 注意事项

- App Store Connect 必须已有可编辑版本
- 上传截图会覆盖同设备类型下已有截图
- 首次建议使用 `--dry-run`
- JWT Token 15 分钟自动刷新

## 常见问题

### 提示 `asc: command not found`

```bash
source ~/.zshrc
```

如果使用 bash：

```bash
source ~/.bash_profile
```

### `install.sh` 与 `asc install` 的区别

- `install.sh`：安装 CLI 工具本体
- `asc install`：初始化当前项目配置

---

更完整的英文文档请查看 `README.md`。
