# 批量订阅商品添加 — 设计文档

**日期**：2026-04-22
**状态**：已批准，进入实施计划

## 1. 目标与范围

在现有 `asc --app <name> iap` 命令上扩展，实现对 App Store Connect 自动续订订阅（Auto-Renewable Subscription）的**批量创建 / 更新**，覆盖完整层级：

- 订阅组（Subscription Group）及其本地化
- 订阅商品（Subscription）及其本地化
- 价格（基准区域 + 基准价格 → Price Point，Apple 自动换算其他区域）
- 入门优惠（Introductory Offer）
- 促销优惠（Promotional Offer）
- 审核截图（Review Screenshot）+ 审核备注（reviewNote）

**范围外**（留待后续迭代）：Offer Code（兑换码）、Tier 直填、价格分区域独立定价。

## 2. 关键决策

| 决策点 | 选择 | 备注 |
|---|---|---|
| 功能范围 | 全量（组 + 订阅 + 本地化 + 价格 + Intro/Promo 优惠 + 审核信息） | 审核信息在 schema 评审时追加为必填 |
| 数据源 | 复用 `data/iap_packages.json`，顶层新增 `subscriptionGroups` 字段 | 与现有一次性 IAP 共存 |
| 已存在条目策略 | 默认只创建、跳过已存在；`--update-existing` 时全量更新 | 价格与优惠变更风险高，默认安全 |
| 价格表达 | 基准区域 `baseTerritory` + 基准金额 `baseAmount`，工具查询 Price Point | Apple 自动跨区换算 |
| 优惠范围 | Introductory + Promotional Offer | Offer Code 独立成期 |
| 文件组织 | 新增 `commands/subscriptions.py`，由 `commands/iap.py` 分发 | 遵循"按命令分文件"项目约定 |

## 3. JSON Schema 扩展

`data/iap_packages.json` 保持向后兼容，顶层可并存 `items`（一次性 IAP）与 `subscriptionGroups`（订阅）。

```json
{
  "items": [
    { "productId": "com.app.coins_100", "inAppPurchaseType": "CONSUMABLE" }
  ],
  "subscriptionGroups": [
    {
      "referenceName": "Pro Membership",
      "localizations": {
        "en-US": { "name": "Pro", "customAppName": "MyApp Pro" },
        "zh-Hans": { "name": "高级会员" }
      },
      "subscriptions": [
        {
          "productId": "com.app.pro.monthly",
          "name": "Pro Monthly",
          "subscriptionPeriod": "ONE_MONTH",
          "groupLevel": 1,
          "familySharable": false,
          "availableInAllTerritories": true,

          "localizations": {
            "en-US": { "name": "Pro Monthly", "description": "Unlock all features." },
            "zh-Hans": { "name": "高级会员（月）", "description": "解锁全部功能。" }
          },

          "price": {
            "baseTerritory": "USA",
            "baseAmount": "9.99"
          },

          "introductoryOffer": {
            "offerMode": "FREE_TRIAL",
            "duration": "ONE_WEEK",
            "numberOfPeriods": 1,
            "territories": ["USA", "CHN"],
            "baseTerritory": "USA",
            "baseAmount": "0.00"
          },

          "promotionalOffers": [
            {
              "referenceName": "Win-back 50off",
              "offerCode": "WINBACK50",
              "offerMode": "PAY_AS_YOU_GO",
              "duration": "ONE_MONTH",
              "numberOfPeriods": 3,
              "baseTerritory": "USA",
              "baseAmount": "4.99"
            }
          ],

          "review": {
            "screenshot": "data/iap_review/pro_monthly.png",
            "note": "Monthly auto-renewable subscription. Test account: test@x.com / pwd123"
          }
        }
      ]
    }
  ]
}
```

### 必填 / 可选字段汇总

| 字段 | 必填 | 说明 |
|---|---|---|
| `subscriptionGroups[].referenceName` | ✅ | ASC 组唯一标识名 |
| `subscriptions[].productId` | ✅ | 订阅商品 ID |
| `subscriptions[].name` | ✅ | 参考名称 |
| `subscriptions[].subscriptionPeriod` | ✅ | 枚举：`ONE_WEEK / ONE_MONTH / TWO_MONTHS / THREE_MONTHS / SIX_MONTHS / ONE_YEAR` |
| `subscriptions[].groupLevel` | ✅ | 组内等级，组内唯一 |
| `subscriptions[].localizations` | ✅ | 至少 1 个 locale，含 `name` + `description` |
| `subscriptions[].price.baseTerritory` + `.baseAmount` | ✅ | 无价格无法提审 |
| `subscriptions[].review.screenshot` | ✅ | 文件存在且可读，PNG/JPG，≤ 5MB |
| `subscriptions[].review.note` | ✅ | 非空字符串 |
| `subscriptions[].familySharable` | ❌ | 默认 false |
| `subscriptions[].availableInAllTerritories` | ❌ | 默认 true |
| `introductoryOffer` | ❌ | 可选；存在则校验其内部字段 |
| `promotionalOffers` | ❌ | 可选；`offerCode` 在同订阅内唯一 |

## 4. `api.py` 新增端点封装

命名风格与现有 `list_in_app_purchases` / `create_in_app_purchase` 保持一致，全部走 `self._request()`（JWT + 429 重试）。

### 订阅组
- `list_subscription_groups(app_id)`
- `create_subscription_group(app_id, reference_name)`
- `update_subscription_group(group_id, attrs)`
- `list_subscription_group_localizations(group_id)`
- `create_subscription_group_localization(group_id, locale, name, custom_app_name=None)`
- `update_subscription_group_localization(loc_id, attrs)`

### 订阅商品
- `list_subscriptions(group_id)`
- `create_subscription(group_id, attrs)`
- `update_subscription(sub_id, attrs)`
- `list_subscription_localizations(sub_id)`
- `create_subscription_localization(sub_id, locale, name, description)`
- `update_subscription_localization(loc_id, attrs)`

### 价格
- `find_subscription_price_point(sub_id, territory, amount)` — 客户端在该订阅的候选 Price Points 中过滤出 `customerPrice == amount`
- `create_subscription_price(sub_id, price_point_id, territory, start_date=None)`
- `list_subscription_prices(sub_id)`
- `delete_subscription_price(price_id)`

### 入门优惠
- `list_subscription_intro_offers(sub_id)`
- `create_subscription_intro_offer(sub_id, attrs, price_point_id=None)`
- `delete_subscription_intro_offer(offer_id)`

### 促销优惠
- `list_subscription_promo_offers(sub_id)`
- `create_subscription_promo_offer(sub_id, attrs, price_point_id)`
- `update_subscription_promo_offer(offer_id, attrs)`
- `delete_subscription_promo_offer(offer_id)`

### 审核截图
- `list_subscription_review_screenshots(sub_id)`
- `create_subscription_review_screenshot_reservation(sub_id, filename, filesize)`
- `upload_subscription_review_screenshot(upload_operations, file_bytes)`
- `commit_subscription_review_screenshot(screenshot_id, source_file_checksum)`
- `delete_subscription_review_screenshot(screenshot_id)`

## 5. 核心流程（`commands/subscriptions.py`）

入口命令保持 `asc --app myapp iap --iap-file ...`，在 `commands/iap.py` 按 JSON 字段分发：
- `items` / 顶层数组 → 现有 `_upload_iap_core`
- `subscriptionGroups` → 新增 `_upload_subscriptions_core`

### Phase 0 · 启动前全量校验（任一失败立即退出）
1. 订阅必填字段齐全
2. 至少 1 个本地化且含 `name` + `description`
3. `price.baseTerritory` + `price.baseAmount` 存在
4. `review.screenshot` 文件存在、可读、格式合法、≤ 5MB；`review.note` 非空
5. 组内 `groupLevel` 唯一；订阅内 `promotionalOffers[].offerCode` 唯一

### Phase 1 · 订阅组
- 以 `referenceName` 为幂等键建索引
- 不存在 → 创建；存在 + `update_existing` → PATCH；存在 + 非 → 跳过
- 同步组本地化（按 locale 索引：创建或更新）

### Phase 2 · 订阅商品主体
- 以 `productId` 为幂等键
- 不存在 → 创建（含 `productId / name / subscriptionPeriod / groupLevel / familySharable / reviewNote / availableInAllTerritories`）
- 存在 + `update_existing` → PATCH 同属性（`productId` 除外）
- 存在 + 非 `update_existing` → 跳过主体写入，但**不阻塞后续阶段的跳过式打印**（保持输出一致）

### Phase 3 · 订阅本地化
- 按 locale 索引，创建或更新 `name` + `description`

### Phase 4 · 价格
- `find_subscription_price_point(sub_id, baseTerritory, baseAmount)`
  - 未命中精确值：报错并列出最近 3 个候选金额供用户调整
- 无现有价格 → create；有 + `update_existing` → delete 再 create；有 + 非 → 跳过

### Phase 5 · 入门优惠
- JSON 未配置 → 跳过
- 无现有 → create（非 `FREE_TRIAL` 需先查 Price Point）
- 有 + `update_existing` → delete 再 create（ASC 不支持 PATCH 入门优惠主体属性）
- 有 + 非 → 跳过

### Phase 6 · 促销优惠
- 以 `offerCode` 索引
- 无 → create；有 + `update_existing` → PATCH 可变属性（金额/周期变更则 delete 重建）；有 + 非 → 跳过

### Phase 7 · 审核截图 + 备注
- `reviewNote` 在 Phase 2 随订阅主体一起写入
- 截图：无 → 预约 + 上传 + `PATCH uploaded=true`；有 + `update_existing` → delete 旧 + 重传；有 + 非 → 跳过

### 错误处理
- 每个订阅独立 try/except，一个失败不中断其它
- 结束时汇总打印失败列表与原因
- 退出码：全部成功 0；有失败 1

### Dry-run
- Phase 0 仍执行（只读校验）
- Phase 1–7 只打印"将创建 / 将更新 / 跳过"，不发写请求
- Price Point 查询仍真实发送（只读），提前暴露匹配失败

## 6. CLI 与输出

### 参数

```
asc --app myapp iap \
    --iap-file data/iap_packages.json \
    [--update-existing]       # 新增，同时作用于 IAP 与订阅两部分
    [--dry-run]
```

- 默认 `--update-existing=false`：仅新建、跳过已存在
- JSON 仅含 `items` → 行为与当前完全一致
- JSON 仅含 `subscriptionGroups` → 仅走订阅流程
- 两者都在 → 先一次性 IAP，再订阅

### 控制台输出示例

```
============================================================
🔁  上传订阅
============================================================

── 订阅组: Pro Membership ──
    不存在，执行创建 ... ✅ ID: 1234567890
    本地化 en-US: 创建 ✅
    本地化 zh-Hans: 创建 ✅

  ── 订阅: com.app.pro.monthly ──
      不存在，执行创建 ... ✅ ID: 9876543210
      本地化 en-US: 创建 ✅
      本地化 zh-Hans: 创建 ✅
      价格: 基准 USA $9.99 → Price Point eyJ... ✅
      入门优惠: FREE_TRIAL / ONE_WEEK ✅
      促销优惠: WINBACK50 ✅
      审核截图: data/iap_review/pro_monthly.png 上传中 ... ✅
      审核备注: 已写入 ✅

============================================================
📊  订阅上传汇总
    订阅组: 1 创建 / 0 更新 / 0 跳过
    订阅:   1 创建 / 0 更新 / 0 跳过 / 0 失败
============================================================
```

## 7. 测试

- `tests/test_subscriptions.py`
  - `_upload_subscriptions_core` 使用 `FakeAPI`（mock `AppStoreConnectAPI`）覆盖：
    - 纯新建路径
    - 存在跳过路径（默认）
    - `update_existing=True` 全量更新路径
  - Phase 0 校验失败：缺审核截图 / 缺本地化 description / Price Point 未命中
  - `dry_run=True` 不触发任何写方法
- `tests/test_iap_dispatch.py`
  - 入口对不同 JSON 结构（仅 items / 仅 subscriptionGroups / 混合）的分发分支

## 8. 文档

- `CLAUDE.md`：在 "Running" 段新增 `--update-existing` 示例；"Data Files" 段补充 `subscriptionGroups` schema 引用
- `README.md`：同步订阅用法示例
- `data/iap_packages.example.json`：新增完整订阅示例，含 intro/promo offer 与 review

## 9. 风险与注意事项

- **Price Point 不一定精确命中 `baseAmount`**：Apple 仅允许固定等级（如 0.99 / 1.99 / 2.99 ...）。未命中时报错并列出最近 3 档候选，要求用户改 `baseAmount`。
- **订阅组 `groupLevel` 不可随意重排**：一旦有提审成功的订阅，改动会触发 ASC 限制。非 `update_existing` 模式严格跳过。
- **促销优惠 `offerCode` 在同订阅内唯一**：作为幂等键。
- **审核截图大小与格式**：ASC 要求 PNG/JPG 且 ≤ 5MB；Phase 0 加校验。
- **Dry-run 会发送只读请求**（Price Point 查询等），以便提前暴露问题，但不发写请求。

## 10. 文件变更清单

新增：
- `src/asc/commands/subscriptions.py`
- `tests/test_subscriptions.py`
- `tests/test_iap_dispatch.py`
- `data/iap_packages.example.json`（若项目已有则扩充）

修改：
- `src/asc/api.py`（新增第 4 节列出的封装方法）
- `src/asc/commands/iap.py`（分发入口 + `--update-existing` 参数）
- `CLAUDE.md`
- `README.md`
