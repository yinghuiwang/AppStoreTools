# 03 IAP 与订阅上传

**适用场景：** 需要在 App Store Connect 中创建或更新一次性内购（IAP）或自动续期订阅。

---

## 前置条件

- 已完成 [01 安装与项目初始化](01-install-and-init.zh-CN.md)
- App 已在 App Store Connect 中存在。命令会创建缺失的 IAP 产品、订阅组和订阅。
- 订阅条目必须配置本地存在的 PNG/JPG/JPEG 审核截图；`--dry-run` 也会验证该文件。

---

## Web 向导（创建 → 编辑 → 上传）

在 Web UI 打开 **IAP**。这是一条可跳步的向导，不是上架页那种本地 / Diff / 上传三个 Tab：

1. **创建**：五个来源 Tab（粘贴商品表 / 从商店导入 / 打开 JSON / 空白新建 / Agent 生成）。商品表会推断类型；**groupLevel 必须按组确认**（1 = 最高，同级 = 平级），不会静默填写。若上次选过的 JSON（或 Profile 默认路径）已有内容，创建步默认选中「打开 JSON」并填好路径，可直接去编辑；否则默认「粘贴商品表」。
2. **编辑**：按订阅组（含嵌套订阅）和一次性 IAP 列出预览。新增 / 编辑在弹窗中改字段与本地化。添加语言会自动翻译展示名（2–30）和描述（≤45）。未配置 LLM 密钥时仍可添加空语言，并提示去设置。
3. **上传**：只看发布清单（新建 / 更新 / 将跳过）。默认 create-only；打开「更新已存在的项目」后才会 PATCH。缺审核截图在同一步折叠补传。

未保存的修改不阻止跳步；真正上传前若有未保存更改，会先保存。

---

---

## 步骤 1：创建 IAP JSON 文件

JSON 顶层可以是一次性 IAP 数组，也可以是包含 `items`、`subscriptionGroups` 或两者的对象。

**仅一次性内购（数组格式）：**

```json
[
  {
    "productId": "com.example.app.coins100",
    "inAppPurchaseType": "CONSUMABLE",
    "name": "100 金币",
    "price": { "baseTerritory": "USA", "baseAmount": "0.99" },
    "localizations": {
      "en-US": { "name": "100 Coins", "description": "Get 100 coins." },
      "zh-Hans": { "name": "100 金币", "description": "获得 100 金币。" }
    }
  }
]
```

**一次性内购 + 订阅（对象格式）：**

```json
{
  "items": [
    {
      "productId": "com.example.app.removeads",
      "inAppPurchaseType": "NON_CONSUMABLE",
      "name": "去除广告",
      "price": { "baseTerritory": "USA", "baseAmount": "2.99" },
      "localizations": {
        "zh-Hans": { "name": "去除广告", "description": "永久去除所有广告。" },
        "en-US": { "name": "Remove Ads", "description": "Remove all ads." }
      }
    }
  ],
  "subscriptionGroups": [
    {
      "referenceName": "高级会员",
      "localizations": {
        "zh-Hans": { "name": "高级会员" },
        "en-US": { "name": "Premium" }
      },
      "subscriptions": [
        {
          "productId": "com.example.app.premium.monthly",
          "name": "高级会员月度",
          "subscriptionPeriod": "ONE_MONTH",
          "groupLevel": 1,
          "price": { "baseTerritory": "USA", "baseAmount": "4.99" },
          "localizations": {
            "zh-Hans": { "name": "高级会员月度", "description": "一个月完整访问权限。" },
            "en-US": { "name": "Premium Monthly", "description": "Full access for one month." }
          },
          "review": {
            "screenshot": "./iap_review/premium_monthly.png",
            "note": "说明审核人员如何访问该订阅。"
          }
        }
      ]
    }
  ]
}
```

将文件保存为 `AppStore/data/iap_packages.json`。`asc init` 会在此生成当前完整模板，其中包含介绍优惠、促销优惠、定价控制和审核截图。相对 `review.screenshot` 路径以 JSON 文件所在目录为基准解析。

---

## 支持的 IAP 类型

| `inAppPurchaseType` 值 | 含义 |
|---|---|
| `CONSUMABLE` | 消耗型（如金币、生命值） |
| `NON_CONSUMABLE` | 非消耗型（如去除广告、解锁功能） |

自动续期订阅放在 `subscriptionGroups` 中，不使用 `inAppPurchaseType`。

---

## 支持的订阅周期

`ONE_WEEK`、`ONE_MONTH`、`TWO_MONTHS`、`THREE_MONTHS`、`SIX_MONTHS`、`ONE_YEAR`

---

## 步骤 2：预览（推荐）

```bash
asc --app myapp iap --iap-file AppStore/data/iap_packages.json --dry-run
```

验证 JSON 和本地审核截图路径，读取当前 App Store Connect 状态并显示执行计划，但不会发送写入请求。

> **重要：** 每条命令都需要 `--app myapp` 标志，除非你已用 `asc app default myapp` 设置了默认 App。`--app` 告诉 `asc` 使用哪个 App Profile（凭证、路径）。详见 [06 多 App Profile 管理](06-multi-app-profiles.zh-CN.md)。

---

## 步骤 3：执行上传

```bash
asc --app myapp iap --iap-file AppStore/data/iap_packages.json
```

默认会创建缺失的 SKU，并补齐已有 SKU 上缺失的本地化/价格。已有名称、本地化、价格和审核图不会改，除非加上 `--update-existing`。Apple 无法替换一次性 IAP 的价格时间表或销售地区；这类更新会失败，而不会报成功。

---

## 常用变体

**覆盖更新已有产品：**

```bash
asc --app myapp iap --iap-file AppStore/data/iap_packages.json --update-existing
```

当需要更新已创建产品的价格、本地化文案或描述时使用此选项。

---

## 上传 App Store 审核截图

使用 `iap-screenshots` 查找仍缺少 App Store 审核截图的 IAP 产品，并上传缺失文件：

```bash
asc --app myapp iap-screenshots
```

该命令会在线查询 App Store Connect 状态，扫描所有缺少 App Store 审核截图的一次性内购和订阅。可选的 `AppStore/data/iap_packages.json` 只按 `productId` 预填 `review.screenshot` 路径；是否缺少截图由 App Store Connect 在线状态决定。

只预览扫描和上传计划，不修改 App Store Connect：

```bash
asc --app myapp iap-screenshots --dry-run
```

使用 IAP JSON 中的路径并以非交互方式执行：

```bash
asc --app myapp iap-screenshots --iap-file AppStore/data/iap_packages.json --no-prompt --yes
```

在 Web UI 中，留在 **上传** 步，展开 **补审核截图**，点击 **扫描缺失**，为需要截图的产品选择 PNG、JPG 或 JPEG 文件，然后点击 **上传截图**。Web UI 中选择的路径只会作为本次上传请求的临时载荷发送，不会写回 `AppStore/data/iap_packages.json`。

---

## 定价说明

设置 `baseTerritory` 为 Apple 三字母地区 ID（如 `"USA"` 或 `"CHN"`）和 `baseAmount`（如 `"0.99"`），工具会自动解析为 Apple 价格点，读取该价格点的 equalizations，并默认为等价地区创建价格（`"applyEqualizedPrices": true`）。价格创建默认使用 Apple 的 inline subscription update 请求（`"creationMode": "inlinePatch"`，`"inlineBatchSize": 50`），如果 inline 创建被拒绝，会自动回退到并发 `subscriptionPrices` POST。如果你已经从 Apple 查询结果或错误信息中拿到了价格点 ID，也可以直接配置 `pricePointId`。

常用美元价格：`0.99`、`1.99`、`2.99`、`4.99`、`9.99`、`14.99`、`19.99`

---

## 常见问题

**Q: 产品被跳过，但实际上不存在**
检查 `productId` 是否与 App Store Connect 中注册的完全一致（区分大小写）。

**Q: `IAP 配置为空`**
JSON 文件中 `items` 或 `subscriptionGroups` 至少需要有一个条目。

**Q: 订阅价格没有更新**
使用 `--update-existing` 选项来覆盖已有价格点。

---

## 下一步

- [04 What's New 与商店 URL](04-whats-new-and-urls.zh-CN.md)
- [05 构建与发布](05-build-and-deploy.zh-CN.md)
