# 05 构建与发布

**适用场景：** 构建 Xcode 项目生成 `.ipa` 文件，并上传到 TestFlight 或 App Store。

---

## 前置条件

- 已完成 [01 安装与项目初始化](01-install-and-init.zh-CN.md)
- Xcode 项目配置了有效的签名证书和预配文件
- macOS（build/deploy 命令仅支持 macOS）

---

## 步骤 1：配置构建默认值（可选但推荐）

编辑项目根目录的 `.asc/config.toml`：

```toml
[build]
project = "MyApp.xcworkspace"
scheme = "MyApp"
output = "build"
signing = "auto"
```

- `project`：`.xcodeproj` 或 `.xcworkspace` 的路径
- `scheme`：Xcode scheme 名称
- `output`：构建产物输出目录
- `signing`：`"auto"`（自动检测）或 `"manual"`（手动选择证书/预配文件）

配置后，后续命令可以省略 `--project` 和 `--scheme`。

---

## 步骤 2：构建应用

**首次运行（交互式，自动检测项目/scheme/签名）：**

```bash
asc build
```

> **注意：** 与元数据/IAP 命令不同，`asc build` **不需要** `--app` 标志，因为它操作的是本地 Xcode 项目，而不是 App Store Connect 凭证。但如果需要使用特定 App Profile 的构建配置，仍可传入 `--app myapp`。

**后续运行（使用缓存配置）：**

```bash
asc build
```

**显式指定项目和 scheme：**

```bash
asc build --project MyApp.xcworkspace --scheme MyApp
```

**非交互模式（需要输入时立即失败）：**

```bash
asc build --no-interactive
```

**强制交互模式（即使在非 TTY shell 中）：**

```bash
asc build --interactive
```

**实时流式输出完整 xcodebuild 日志：**

```bash
asc build --verbose
```

输出产物：

```
build/
├── MyApp.xcarchive
├── export/
│   └── MyApp.ipa
├── build.log
└── export.log
```

---

## 步骤 3：上传到 TestFlight 或 App Store

**上传 .ipa 文件：**

```bash
asc --app myapp deploy --ipa build/export/MyApp.ipa
```

> **重要：** 这里需要 `--app myapp` 标志，因为 `asc deploy` 需要你的 App Store Connect 凭证来上传 .ipa。详见 [06 多 App Profile 管理](06-multi-app-profiles.zh-CN.md)。

**指定目标（TestFlight 或 App Store）：**

```bash
asc deploy --ipa build/export/MyApp.ipa --destination testflight
asc deploy --ipa build/export/MyApp.ipa --destination appstore
```

**实时流式输出上传日志：**

```bash
asc deploy --ipa build/export/MyApp.ipa --verbose
```

---

## 步骤 4：一条命令完成构建 + 上传

```bash
asc --app myapp release --scheme MyApp --destination testflight
```

这会自动执行 `build` 然后 `deploy`。

> **重要：** 需要 `--app myapp` 标志，因为 `asc release` 的 deploy 步骤需要 App Store Connect 凭证。

**带详细日志输出：**

```bash
asc release --scheme MyApp --destination testflight --verbose
```

**预览模式（验证但不上传）：**

```bash
asc release --scheme MyApp --dry-run
```

---

## 日志与故障排查

构建日志保存在：

- `build/build.log` — xcodebuild archive 输出
- `build/export.log` — xcodebuild export 输出
- `build/upload.log` — 上传输出

失败时会自动打印最后 20 行日志。使用 `--verbose` 可实时流式输出完整日志。

---

## 常见问题

**Q: `❌ 此命令仅支持 macOS`**
Build/deploy 命令仅在 macOS 上可用，元数据上传在 Linux/Windows 也可用。

**Q: `❌ No matching archive found`**
工具在 `output` 目录中查找 `.xcarchive` 文件，确保构建步骤成功完成。

**Q: 签名证书未找到**
检查证书是否已安装在 Keychain 中，预配文件是否有效。使用 `--interactive` 手动选择。

**Q: `--verbose` 没有输出**
子进程输出正在实时流式传输。如果看起来卡住了，检查 `build/` 目录中的日志文件。

---

## 下一步

- [06 多 App Profile 管理](06-multi-app-profiles.zh-CN.md)
- [07 Guard 安全守卫](07-guard-security.zh-CN.md)
- [08 CI/CD 自动化](08-ci-cd.zh-CN.md)
