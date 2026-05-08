# 03 IAP 与订阅上传

**适用场景：** 需要在 App Store Connect 中创建或更新一次性内购（IAP）或自动续期订阅。

---

## 前置条件

- 已完成 [01 安装与项目初始化](01-install-and-init.zh-CN.md)
- App 已在 App Store Connect 中存在（工具会自动创建缺失的 IAP 产品，但 App 本身必须已存在）

---

## 步骤 1：创建 IAP JSON 文件

工具从 JSON 文件读取配置，支持三种顶层结构：

**仅一次性内购（数组格式）：**

```json
[
  {
    "productId": "com.example.app.coins100",
    "type": "CONSUMABLE",
    "name": "100 金币",
    "price": { "baseTerritory": "USA", "baseAmount": "0.99" },
    "localizations": [
      { "locale": "en-US", "name": "100 Coins", "description": "Get 100 coins." },
      { "locale": "zh-Hans", "name": "100 金币", "description": "获得 100 金币。" }
    ]
  }
]
```

**一次性内购 + 订阅（对象格式）：**

```json
{
  "items": [
    {
      "productId": "com.example.app.removeads",
      "type": "NON_CONSUMABLE",
      "name": "去除广告",
      "price": { "baseTerritory": "USA", "baseAmount": "2.99" },
      "localizations": [
        { "locale": "zh-Hans", "name": "去除广告", "description": "永久去除所有广告。" },
        { "locale": "en-US", "name": "Remove Ads", "description": "Remove all ads." }
      ]
    }
  ],
  "subscriptionGroups": [
    {
      "referenceName": "高级会员",
      "localizations": [
        { "locale": "zh-Hans", "name": "高级会员" },
        { "locale": "en-US", "name": "Premium" }
      ],
      "subscriptions": [
        {
          "productId": "com.example.app.premium.monthly",
          "referenceName": "高级会员月度",
          "duration": "ONE_MONTH",
          "price": { "baseTerritory": "USA", "baseAmount": "4.99" },
          "localizations": [
            { "locale": "zh-Hans", "name": "高级会员月度", "description": "一个月完整访问权限。" },
            { "locale": "en-US", "name": "Premium Monthly", "description": "Full access for one month." }
          ]
        }
      ]
    }
  ]
}
```

将文件保存为 `data/iap_packages.json`。完整 schema（含介绍优惠、促销优惠、审核截图）请参考 `data/iap_packages.example.json`。

---

## 支持的 IAP 类型

| `type` 值 | 含义 |
|---|---|
| `CONSUMABLE` | 消耗型（如金币、生命值） |
| `NON_CONSUMABLE` | 非消耗型（如去除广告、解锁功能） |
| `AUTO_RENEWABLE_SUBSCRIPTION` | 自动续期订阅（放在 `subscriptionGroups` 中） |

---

## 支持的订阅周期

`THREE_DAYS`、`ONE_WEEK`、`TWO_WEEKS`、`ONE_MONTH`、`TWO_MONTHS`、`THREE_MONTHS`、`SIX_MONTHS`、`ONE_YEAR`

---

## 步骤 2：预览（推荐）

```bash
asc --app myapp iap --iap-file data/iap_packages.json --dry-run
```

验证 JSON 结构并显示将要创建/更新的内容，不会实际调用 API。

> **重要：** 每条命令都需要 `--app myapp` 标志，除非你已用 `asc app default myapp` 设置了默认 App。`--app` 告诉 `asc` 使用哪个 App Profile（凭证、路径）。详见 [06 多 App Profile 管理](06-multi-app-profiles.zh-CN.md)。

---

## 步骤 3：执行上传

```bash
asc --app myapp iap --iap-file data/iap_packages.json
```

默认行为是**仅创建**：已存在的产品会被跳过。

---

## 常用变体

**覆盖更新已有产品：**

```bash
asc --app myapp iap --iap-file data/iap_packages.json --update-existing
```

当需要更新已创建产品的价格、本地化文案或描述时使用此选项。

---

## 定价说明

设置 `baseTerritory`（如 `"USA"`）和 `baseAmount`（如 `"0.99"`），工具会自动解析为 Apple 价格点，Apple 负责其他地区的自动换算。

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
