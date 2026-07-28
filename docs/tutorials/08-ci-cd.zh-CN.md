# 08 CI/CD 自动化

**适用场景：** 在 GitHub Actions 或其他 CI/CD 流水线中自动化元数据上传和应用发布。

---

## 前置条件

- 已完成 [01 安装与项目初始化](01-install-and-init.zh-CN.md)
- 了解 [07 Guard 安全守卫](07-guard-security.zh-CN.md)（CI 环境需要关闭 Guard）

---

## 核心原则

CI 环境中：

1. **用 Secrets 创建临时 App Profile**，非交互命令仍需要可解析的 Profile；不要提交生成的 `.toml` 或 `.p8` 文件
2. **关闭 Guard**（`ASC_GUARD_DISABLE=1`），因为 CI 机器和 IP 每次都会变化
3. **显式传入 `--app ci`**，不要依赖交互式 Profile 选择器
4. **对 `build` 或 `release` 使用 `--no-interactive`**，缺少构建输入时直接失败

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

      - name: Configure ephemeral asc profile
        env:
          ASC_ISSUER_ID: ${{ secrets.ASC_ISSUER_ID }}
          ASC_KEY_ID: ${{ secrets.ASC_KEY_ID }}
          ASC_KEY_P8: ${{ secrets.ASC_KEY_P8 }}
          ASC_APP_ID: ${{ secrets.ASC_APP_ID }}
        run: |
          asc_config_dir="$HOME/.config/asc"
          mkdir -p "$asc_config_dir/keys" "$asc_config_dir/profiles"
          printf '%s\n' "$ASC_KEY_P8" > "$asc_config_dir/keys/AuthKey.p8"
          chmod 600 "$asc_config_dir/keys/AuthKey.p8"
          {
            printf '[credentials]\n'
            printf 'issuer_id = "%s"\n' "$ASC_ISSUER_ID"
            printf 'key_id = "%s"\n' "$ASC_KEY_ID"
            printf 'key_file = "%s/keys/AuthKey.p8"\n' "$asc_config_dir"
            printf 'app_id = "%s"\n\n' "$ASC_APP_ID"
            printf '[defaults]\n'
            printf 'csv = "%s/AppStore/data/appstore_info.csv"\n' "$GITHUB_WORKSPACE"
            printf 'screenshots = "%s/AppStore/data/screenshots"\n' "$GITHUB_WORKSPACE"
          } > "$asc_config_dir/profiles/ci.toml"

      - name: Upload metadata
        env:
          ASC_GUARD_DISABLE: "1"
        run: asc --app ci upload --dry-run  # 验证后移除 --dry-run
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
          PROVISIONING_PROFILE_BASE64: ${{ secrets.PROVISIONING_PROFILE_BASE64 }}
        run: |
          printf '%s' "$CERTIFICATE_P12" | base64 -D > "$RUNNER_TEMP/cert.p12"
          printf '%s' "$PROVISIONING_PROFILE_BASE64" | base64 -D > "$RUNNER_TEMP/AppStore.mobileprovision"
          security cms -D -i "$RUNNER_TEMP/AppStore.mobileprovision" > "$RUNNER_TEMP/profile.plist"
          profile_uuid=$(/usr/libexec/PlistBuddy -c 'Print :UUID' "$RUNNER_TEMP/profile.plist")
          mkdir -p "$HOME/Library/MobileDevice/Provisioning Profiles"
          cp "$RUNNER_TEMP/AppStore.mobileprovision" "$HOME/Library/MobileDevice/Provisioning Profiles/$profile_uuid.mobileprovision"
          security create-keychain -p "" build.keychain
          security import "$RUNNER_TEMP/cert.p12" -k build.keychain -P "$CERTIFICATE_PASSWORD" -T /usr/bin/codesign
          security list-keychains -d user -s build.keychain
          security default-keychain -s build.keychain
          security set-keychain-settings -t 3600 -u build.keychain
          security unlock-keychain -p "" build.keychain
          security set-key-partition-list -S apple-tool:,apple: -s -k "" build.keychain

      - name: Configure ephemeral asc profile
        env:
          ASC_ISSUER_ID: ${{ secrets.ASC_ISSUER_ID }}
          ASC_KEY_ID: ${{ secrets.ASC_KEY_ID }}
          ASC_KEY_P8: ${{ secrets.ASC_KEY_P8 }}
          ASC_APP_ID: ${{ secrets.ASC_APP_ID }}
        run: |
          asc_config_dir="$HOME/.config/asc"
          mkdir -p "$asc_config_dir/keys" "$asc_config_dir/profiles"
          printf '%s\n' "$ASC_KEY_P8" > "$asc_config_dir/keys/AuthKey.p8"
          chmod 600 "$asc_config_dir/keys/AuthKey.p8"
          {
            printf '[credentials]\n'
            printf 'issuer_id = "%s"\n' "$ASC_ISSUER_ID"
            printf 'key_id = "%s"\n' "$ASC_KEY_ID"
            printf 'key_file = "%s/keys/AuthKey.p8"\n' "$asc_config_dir"
            printf 'app_id = "%s"\n' "$ASC_APP_ID"
          } > "$asc_config_dir/profiles/ci.toml"

      - name: Build and upload to TestFlight
        env:
          ASC_GUARD_DISABLE: "1"
        run: |
          asc --app ci release \
            --scheme MyApp \
            --destination testflight \
            --signing manual \
            --profile "$RUNNER_TEMP/AppStore.mobileprovision" \
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
| `PROVISIONING_PROFILE_BASE64` | Base64 编码的 App Store `.mobileprovision` 文件（仅 build 场景需要） |

---

## CI 环境变量参考

| 变量名 | 含义 |
|---|---|
| `ASC_ISSUER_ID` | 用于生成 `ci.toml` 的 App Store Connect Issuer ID |
| `ASC_KEY_ID` | 用于生成 `ci.toml` 的 API Key ID |
| `ASC_KEY_P8` | 写入临时密钥文件的私钥内容 |
| `ASC_APP_ID` | 用于生成 `ci.toml` 的 App 数字 ID |
| `ASC_GUARD_DISABLE` | 设为 `1` 关闭 Guard（CI 必须设置） |
| `ASC_LANG` | 界面语言（`zh` 或 `en`） |

---

## 常见问题

**Q: 如何安全地存储 `.p8` 文件内容？**
将 `.p8` 文件的完整内容（包括 `-----BEGIN PRIVATE KEY-----` 和 `-----END PRIVATE KEY-----`）粘贴到 GitHub Secret 中。示例使用 `printf` 写入，以保留多行内容且不在日志中暴露私钥。

**Q: 元数据上传失败，提示找不到可编辑版本**
确保 App Store Connect 中有处于 `PREPARE_FOR_SUBMISSION` 状态的版本，或在 CI 触发前手动创建版本。

**Q: build 命令在 CI 中卡住**
使用 `--no-interactive` 标志，这样在需要用户输入时会立即失败而不是等待。

---

## 下一步

- [07 Guard 安全守卫](07-guard-security.zh-CN.md)
- [返回教程索引](README.zh-CN.md)
