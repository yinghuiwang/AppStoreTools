# 06 多 App Profile 管理

**适用场景：** 管理多个 App 或在不同的 App Store Connect 凭证间切换。

---

## 前置条件

- 已完成 [01 安装与项目初始化](01-install-and-init.zh-CN.md)

---

## 步骤 1：列出所有 Profile

```bash
asc app list
```

显示所有已配置的 App Profile 及其存储位置。

---

## 步骤 2：添加新 Profile

```bash
asc app add production-app
```

按提示输入凭证和数据路径。Profile 会保存到 `~/.config/asc/profiles/production-app.toml`。

---

## 步骤 3：查看 Profile 详情

```bash
asc app show production-app
```

显示 Profile 的完整配置。

---

## 步骤 4：编辑 Profile

```bash
asc app edit production-app
```

交互式更新凭证、路径或其他设置。

---

## 步骤 5：设置默认 App

```bash
asc app default production-app
```

设置后，所有命令都可以省略 `--app`：

```bash
asc upload              # 使用 production-app
asc screenshots         # 使用 production-app
asc build               # 使用 production-app
```

查看当前默认 App：

```bash
asc app list
```

默认 App 会用 `*` 标记。

---

## 步骤 6：在 App 间切换

使用 `--app` 覆盖默认值：

```bash
asc --app staging-app upload
asc --app staging-app screenshots
```

---

## 步骤 7：删除 Profile

```bash
asc app remove old-app
```

这会从 `~/.config/asc/profiles/` 中删除 Profile，但不会影响 `.p8` 密钥文件。

---

## Profile 存储位置

- **全局 Profile：** `~/.config/asc/profiles/<name>.toml`
- **API 密钥：** `~/.config/asc/keys/`（从原始位置复制）
- **本地项目配置：** `.asc/config.toml`（可选，覆盖全局设置）

---

## 本地项目配置（`.asc/config.toml`）

你也可以在项目中存储 App 特定的设置：

```toml
[defaults]
default_app = "myapp"

[build]
project = "MyApp.xcworkspace"
scheme = "MyApp"
output = "build"
signing = "auto"
```

对于当前项目，这会优先于全局 Profile。

---

## 常见问题

**Q: 不同 App 能否使用不同的 CSV/截图路径？**
可以。每个 Profile 存储自己的 `csv` 和 `screenshots` 路径。添加 Profile 时设置，或稍后用 `asc app edit` 修改。

**Q: 凭证存储在哪里？**
Profile 在 `~/.config/asc/profiles/`（可读的 TOML 格式），API 密钥在 `~/.config/asc/keys/`（`.p8` 文件）。不要将这些提交到 git。

**Q: 能否从另一台机器导入 Profile？**
可以。从 `~/.config/asc/profiles/` 复制 `.toml` 文件，从 `~/.config/asc/keys/` 复制对应的 `.p8` 密钥到新机器的相同位置。

---

## 下一步

- [07 Guard 安全守卫](07-guard-security.zh-CN.md)
- [02 元数据与截图上传](02-metadata-and-screenshots.zh-CN.md)
