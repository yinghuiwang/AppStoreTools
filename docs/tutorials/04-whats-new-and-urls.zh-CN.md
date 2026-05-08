# 04 What's New 与商店 URL

**适用场景：** 更新版本说明（What's New）和商店 URL（技术支持、营销网站、隐私政策）。

---

## 前置条件

- 已完成 [01 安装与项目初始化](01-install-and-init.zh-CN.md)
- App Store Connect 中有可编辑的 App 版本

---

## 步骤 1：更新 What's New（版本说明）

**单语言，直接输入文本：**

```bash
asc --app myapp whats-new --text "修复已知问题，提升性能。"
```

**多语言，直接输入文本：**

```bash
asc --app myapp whats-new --text "Bug fixes." --locales en-US zh-Hans
```

**多语言，从文件读取：**

创建 `data/whats_new.txt`：

```
en-US:
- Bug fixes
- Performance improvements
---
zh-Hans:
- 修复已知问题
- 性能优化
```

然后运行：

```bash
asc --app myapp whats-new --file data/whats_new.txt
```

---

## 步骤 2：设置商店 URL

**技术支持 URL：**

```bash
asc --app myapp set-support-url --text "https://example.com/support"
```

**营销网站（支持多语言）：**

```bash
asc --app myapp set-marketing-url --text "https://example.com" --locales en-US zh-Hans
```

**隐私政策 URL：**

```bash
asc --app myapp set-privacy-policy-url --text "https://example.com/privacy"
```

---

## 步骤 3：查看当前 URL

```bash
asc --app myapp support-url
asc --app myapp marketing-url
asc --app myapp privacy-policy-url
```

---

## 常见问题

**Q: `whats_new.txt` 格式无法识别**
确保每个语言区块以 `---`（单独一行三个破折号）结尾，语言代码必须与 App Store Connect 中的语言一致。

**Q: URL 没有更新**
URL 是 App 级别的设置，不是版本级别的，修改会立即生效。

---

## 下一步

- [05 构建与发布](05-build-and-deploy.zh-CN.md)
- [02 元数据与截图上传](02-metadata-and-screenshots.zh-CN.md)
