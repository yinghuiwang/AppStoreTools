# 构建与发布命令设计文档

**日期：** 2026-04-23
**状态：** 已批准

## 概述

新增三条命令，实现从 Xcode 源码到 App Store / TestFlight 的完整发布流程：

| 命令 | 职责 |
|------|------|
| `asc build` | 构建 `.xcarchive` + 导出 `.ipa` |
| `asc deploy` | 上传已有 `.ipa` 到 TestFlight 或 App Store |
| `asc release` | 串联 build + deploy，一键发布 |

所有命令集成进现有 `asc` CLI，共享 profile 凭证配置，仅支持 macOS。

---

## 第一部分：`asc build`

**职责：** 从源码构建 `.xcarchive`，再导出 `.ipa`。

**命令签名：**
```bash
asc build \
  --project <path>                     # .xcodeproj 或 .xcworkspace 路径
  --scheme <name>                      # Xcode Scheme 名称
  --configuration Release              # 构建配置（默认 Release）
  --output <dir>                       # 输出目录（默认 ./build）
  --signing auto|manual                # 签名方式（默认 auto）
  --profile <path>                     # 手动签名：Provisioning Profile 路径
  --certificate <name>                 # 手动签名：证书名称
  --destination testflight|appstore    # 导出类型（默认 appstore）
  --dry-run                            # 打印命令但不执行
```

**执行流程：**
1. 检测项目类型：`.xcworkspace` 优先，否则用 `.xcodeproj`
2. 自动发现 Scheme：未指定时列出可用 Scheme，提示用户选择
3. 运行 `xcodebuild archive`，生成 `.xcarchive`
4. 根据签名方式生成 `ExportOptions.plist`：
   - `auto`：`<key>method</key><string>app-store-connect</string>` + `<key>signingStyle</key><string>automatic</string>`
   - `manual`：添加 `provisioningProfiles` 和 `signingCertificate` 字段
5. 运行 `xcodebuild -exportArchive`，生成 `.ipa`
6. 打印 `.ipa` 输出路径

**profile 配置支持（`.asc/config.toml`）：**
```toml
[build]
project = "MyApp.xcworkspace"
scheme = "MyApp"
output = "build"
signing = "auto"
```

**退出码：**
- `0` — 成功
- `1` — 构建失败（xcodebuild 错误）
- `2` — 非 macOS 平台

---

## 第二部分：`asc deploy`

**职责：** 上传 `.ipa` 到 TestFlight 或 App Store。复用现有 profile 凭证，无需额外配置。

**命令签名：**
```bash
asc deploy \
  --ipa <path>                          # .ipa 文件路径（必填）
  --destination testflight|appstore     # 上传目标（默认 testflight）
  --dry-run                             # 打印上传信息但不实际上传
```

**执行流程：**
1. 验证 `.ipa` 文件存在且为有效格式
2. 从现有 profile 读取凭证：`issuer_id`、`key_id`、`key_file`（`.p8` 路径）
3. 优先使用 `xcrun notarytool`（macOS 13+），自动降级到 `xcrun altool`（旧版系统）
4. 执行上传命令
5. 轮询上传状态（每 30 秒检查一次），超时上限 30 分钟
6. 成功后打印 TestFlight build 号或 App Store 提交状态

**认证：** 复用 `~/.config/asc/profiles/<name>.toml` 中的 `issuer_id`、`key_id`、`key_file`，与元数据上传共享同一套凭证。

**退出码：**
- `0` — 上传成功
- `1` — 上传失败
- `2` — 非 macOS 平台

---

## 第三部分：`asc release`

**职责：** 串联 `build` + `deploy`，提供完整一键发布。内部调用 `build_core()` 和 `deploy_core()`，不重复实现逻辑。

**命令签名：**
```bash
asc release \
  --project <path>
  --scheme <name>
  --destination testflight|appstore    # 同时控制导出类型和上传目标（默认 testflight）
  --signing auto|manual
  --profile <path>
  --certificate <name>
  --output <dir>
  --dry-run
```

**执行流程：**
```
asc release
  └── build_core()   →  生成 .ipa 到 <output>/
  └── deploy_core()  →  上传 .ipa 到目标平台
```

**日常最短用法（配置了 profile 默认值后）：**
```bash
asc release --destination testflight
```

---

## 实现架构

**新增文件：**
- `src/asc/commands/build.py`：包含所有核心函数和命令函数

**核心函数（内部，可被 mock 测试）：**
- `detect_project(path) -> tuple[str, str]`：返回 `(project_path, project_type)`
- `list_schemes(project_path) -> list[str]`：列出可用 Scheme
- `run_xcodebuild_archive(project, scheme, config, output, signing_opts) -> Path`：返回 `.xcarchive` 路径
- `generate_export_options(signing, destination, profile, certificate) -> Path`：生成 `ExportOptions.plist`，返回文件路径
- `run_xcodebuild_export(archive_path, export_options, output) -> Path`：返回 `.ipa` 路径
- `build_core(...)  -> Path`：串联 archive + export，返回 `.ipa` 路径
- `upload_ipa(ipa_path, issuer_id, key_id, key_file, destination) -> None`：执行上传
- `deploy_core(...)  -> None`：验证 + 读凭证 + 上传

**命令函数（typer 注册）：**
- `cmd_build(...)` → 注册为 `asc build`
- `cmd_deploy(...)` → 注册为 `asc deploy`
- `cmd_release(...)` → 注册为 `asc release`

**修改文件：**
- `src/asc/cli.py`：导入并注册三条新命令
- `src/asc/config.py`：新增读取 `[build]` section 的属性

**平台检查：** 所有命令入口处检查 `sys.platform`，非 macOS 时打印明确错误并以退出码 `2` 退出。

---

## 涉及文件

| 文件 | 操作 |
|------|------|
| `src/asc/commands/build.py` | 新建 |
| `src/asc/cli.py` | 新增导入和命令注册 |
| `src/asc/config.py` | 新增 `[build]` section 属性 |
| `tests/test_build.py` | 新建，mock xcodebuild 调用 |
