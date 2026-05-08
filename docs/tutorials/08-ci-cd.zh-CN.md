# 08 CI/CD 自动化

**适用场景：** 在 GitHub Actions 或其他 CI/CD 流水线中自动化元数据上传和应用发布。

---

## 前置条件

- 已完成 [01 安装与项目初始化](01-install-and-init.zh-CN.md)
- 了解 [07 Guard 安全守卫](07-guard-security.zh-CN.md)（CI 环境需要关闭 Guard）

---

## 核心原则

CI 环境中：
1. **通过环境变量注入凭证**，不要将 `.toml` 或 `.p8` 文件提交到仓库
2. **关闭 Guard**（`ASC_GUARD_DISABLE=1`），因为 CI 机器和 IP 每次都会变化
3. **使用 `--no-interactive`**，避免命令等待用户输入

---

## GitHub Actions 示例

### 场景 A：上传元数据 + 截图

```yaml
# .github/workflows/upload-metadata.yml
name: Upload App Store Metadata

on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  upload:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install asc
        run: pip install git+https://github.com/yinghuiwang/AppStoreTools.git

      - name: Write API key file
        run: |
          mkdir -p ~/.config/asc/keys
          echo "${{ secrets.ASC_KEY_P8 }}" > ~/.config/asc/keys/AuthKey.p8
          chmod 600 ~/.config/asc/keys/AuthKey.p8

      - name: Upload metadata
        env:
          ISSUER_ID: ${{ secrets.ASC_ISSUER_ID }}
          KEY_ID: ${{ secrets.ASC_KEY_ID }}
          KEY_FILE: ~/.config/asc/keys/AuthKey.p8
          APP_ID: ${{ secrets.ASC_APP_ID }}
          ASC_GUARD_DISABLE: "1"
        run: asc upload --dry-run  # 改为 asc upload 正式上传
```

### 场景 B：构建并上传到 TestFlight（macOS runner）

```yaml
# .github/workflows/release-testflight.yml
name: Release to TestFlight

on:
  push:
    tags:
      - "v*"

jobs:
  release:
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install asc
        run: pip install git+https://github.com/yinghuiwang/AppStoreTools.git

      - name: Import signing certificate
        env:
          CERTIFICATE_P12: ${{ secrets.CERTIFICATE_P12 }}
          CERTIFICATE_PASSWORD: ${{ secrets.CERTIFICATE_PASSWORD }}
        run: |
          echo "$CERTIFICATE_P12" | base64 --decode > /tmp/cert.p12
          security create-keychain -p "" build.keychain
          security import /tmp/cert.p12 -k build.keychain -P "$CERTIFICATE_PASSWORD" -T /usr/bin/codesign
          security list-keychains -s build.keychain
          security set-keychain-settings -t 3600 -u build.keychain
          security unlock-keychain -p "" build.keychain

      - name: Write API key file
        run: |
          mkdir -p ~/.config/asc/keys
          echo "${{ secrets.ASC_KEY_P8 }}" > ~/.config/asc/keys/AuthKey.p8
          chmod 600 ~/.config/asc/keys/AuthKey.p8

      - name: Build and upload to TestFlight
        env:
          ISSUER_ID: ${{ secrets.ASC_ISSUER_ID }}
          KEY_ID: ${{ secrets.ASC_KEY_ID }}
          KEY_FILE: ~/.config/asc/keys/AuthKey.p8
          APP_ID: ${{ secrets.ASC_APP_ID }}
          ASC_GUARD_DISABLE: "1"
        run: |
          asc release \
            --scheme MyApp \
            --destination testflight \
            --no-interactive \
            --verbose
```

---

## 需要在 GitHub 仓库中配置的 Secrets

| Secret 名称 | 内容 |
|---|---|
| `ASC_ISSUER_ID` | App Store Connect Issuer ID |
| `ASC_KEY_ID` | API Key ID |
| `ASC_KEY_P8` | `.p8` 私钥文件的完整内容（包含 `-----BEGIN PRIVATE KEY-----` 头尾） |
| `ASC_APP_ID` | App 的数字 ID |
| `CERTIFICATE_P12` | 签名证书（Base64 编码的 `.p12` 文件，仅 build 场景需要） |
| `CERTIFICATE_PASSWORD` | `.p12` 文件的密码（仅 build 场景需要） |

---

## 环境变量参考

| 变量名 | 含义 |
|---|---|
| `ISSUER_ID` | App Store Connect Issuer ID |
| `KEY_ID` | API Key ID |
| `KEY_FILE` | `.p8` 私钥文件路径 |
| `APP_ID` | App 数字 ID |
| `ASC_GUARD_DISABLE` | 设为 `1` 关闭 Guard（CI 必须设置） |
| `ASC_LANG` | 界面语言（`zh` 或 `en`） |

---

## 常见问题

**Q: 如何安全地存储 `.p8` 文件内容？**
将 `.p8` 文件的完整内容（包括 `-----BEGIN PRIVATE KEY-----` 和 `-----END PRIVATE KEY-----`）粘贴到 GitHub Secret 中，然后在 CI 中用 `echo "$SECRET" > file.p8` 写入文件。

**Q: 元数据上传失败，提示找不到可编辑版本**
确保 App Store Connect 中有处于 `PREPARE_FOR_SUBMISSION` 状态的版本，或在 CI 触发前手动创建版本。

**Q: build 命令在 CI 中卡住**
使用 `--no-interactive` 标志，这样在需要用户输入时会立即失败而不是等待。

---

## 下一步

- [07 Guard 安全守卫](07-guard-security.zh-CN.md)
- [返回教程索引](README.zh-CN.md)
