# 02 元数据与截图上传

**适用场景：** 已完成凭证配置，需要将应用名称、副标题、描述、关键词和截图上传到 App Store Connect。

---

## 前置条件

- 已完成 [01 安装与项目初始化](01-install-and-init.zh-CN.md)
- App Store Connect 中有可编辑的 App 版本（状态为 `PREPARE_FOR_SUBMISSION`、`REJECTED` 等）

---

## 步骤 1：填写元数据 CSV

编辑 `data/appstore_info.csv`，必填列：

| 列名 | 含义 |
|---|---|
| `语言` | 语言区域，格式为 `显示名称(代码)`，例如 `简体中文(zh-Hans)` 或 `English(en-US)` |
| `应用名称` | App 名称（最多 30 字符） |
| `副标题` | 副标题（最多 30 字符） |
| `长描述` | 完整描述（最多 4000 字符） |
| `关键子` | 关键词，逗号分隔（总计最多 100 字符） |

可选列：

| 列名 | 含义 |
|---|---|
| `技术支持链接` | 技术支持 URL |
| `营销网站` | 营销网站 URL |
| `隐私政策网址` | 隐私政策 URL |

示例行：

```
语言,应用名称,副标题,长描述,关键子
English(en-US),My App,The best app,A full description here.,productivity,tools
简体中文(zh-Hans),我的应用,最好的应用,完整描述。,效率,工具
```

---

## 步骤 2：准备截图

将截图放入 `data/screenshots/<语言文件夹>/`：

| 文件夹名 | 对应语言 |
|---|---|
| `cn` | `zh-Hans` |
| `en-US` | `en-US` |
| `ja` | `ja` |
| `ko` | `ko` |

设备类型根据**图片尺寸自动识别**：

| 设备类型 | 分辨率 |
|---|---|
| `APP_IPHONE_67` | 1290×2796 或 1320×2868 |
| `APP_IPHONE_65` | 1284×2778 或 1242×2688 |
| `APP_IPHONE_61` | 1179×2556 或 1170×2532 |
| `APP_IPHONE_58` | 1125×2436 |
| `APP_IPHONE_55` | 1242×2208 |
| `APP_IPAD_PRO_3GEN_129` | 2048×2732 |
| `APP_IPAD_PRO_3GEN_11` | 1668×2388 |

文件名以数字开头可控制上传顺序：

```
data/screenshots/cn/
├── 01_首页.png
├── 02_详情.png
└── 03_设置.png
```

---

## 步骤 3：先做预览（推荐）

正式上传前先用 `--dry-run` 验证：

```bash
asc --app myapp upload --dry-run
```

这会验证凭证、CSV 格式和截图路径，不会实际修改任何内容。

> **重要：** 每条命令都需要 `--app myapp` 标志，除非你已用 `asc app default myapp` 设置了默认 App。`--app` 告诉 `asc` 使用哪个 App Profile（凭证、路径）。详见 [06 多 App Profile 管理](06-multi-app-profiles.zh-CN.md)。

---

## 步骤 4：执行上传

```bash
asc --app myapp upload
```

一次性完成元数据 + 截图的全量上传。

---

## 常用变体

**仅上传元数据（不含截图）：**

```bash
asc --app myapp metadata
```

**仅更新关键词：**

```bash
asc --app myapp keywords
```

**仅上传截图：**

```bash
asc --app myapp screenshots
```

**只上传指定设备类型的截图：**

```bash
asc --app myapp screenshots --display-type APP_IPHONE_67
```

**使用自定义 CSV 路径：**

```bash
asc --app myapp metadata --csv /path/to/custom.csv
```

**使用自定义截图目录：**

```bash
asc --app myapp screenshots --screenshots /path/to/custom/screenshots
```

---

## 上传流程说明

1. 读取 CSV，解析语言区域代码
2. 通过 ASC API 找到可编辑的 App 版本
3. 逐语言创建或更新元数据字段
4. 截图上传：先删除目标设备类型的现有截图，再按文件名顺序上传新截图

> **注意：** 截图上传会**替换**同设备类型下的所有现有截图。如有需要，请在运行前备份现有截图。

---

## 常见问题

**Q: `❌ 找不到可编辑的 App Store 版本`**
App 版本必须已在 App Store Connect 中存在且处于可编辑状态，请先手动创建版本。

**Q: 部分语言被跳过**
CSV 中 `语言` 列的语言代码必须与 App Store Connect 中已添加的语言一致，请先在 App Store Connect 中添加缺失的语言。

**Q: 截图尺寸无法识别**
检查图片尺寸是否与上表中的支持分辨率完全匹配，导出时不要缩放（使用 1x 原始尺寸）。

---

## 下一步

- [03 IAP 与订阅上传](03-iap-and-subscriptions.zh-CN.md)
- [04 What's New 与商店 URL](04-whats-new-and-urls.zh-CN.md)
