# 03 IAP & Subscriptions

**When to use:** You need to create or update In-App Purchases (one-time) or auto-renewable subscriptions in App Store Connect.

---

## Prerequisites

- Completed [01 Install & Project Init](01-install-and-init.md)
- IAP products or subscription groups already created in App Store Connect (the tool creates missing ones, but the app must exist)

---

## Step 1: Create the IAP JSON file

The tool reads from a JSON file. Three supported top-level structures:

**One-time IAP only (array):**

```json
[
  {
    "productId": "com.example.app.coins100",
    "type": "CONSUMABLE",
    "name": "100 Coins",
    "price": { "baseTerritory": "USA", "baseAmount": "0.99" },
    "localizations": [
      { "locale": "en-US", "name": "100 Coins", "description": "Get 100 coins." },
      { "locale": "zh-Hans", "name": "100 金币", "description": "获得 100 金币。" }
    ]
  }
]
```

**One-time IAP + subscriptions (object):**

```json
{
  "items": [
    {
      "productId": "com.example.app.removeads",
      "type": "NON_CONSUMABLE",
      "name": "Remove Ads",
      "price": { "baseTerritory": "USA", "baseAmount": "2.99" },
      "localizations": [
        { "locale": "en-US", "name": "Remove Ads", "description": "Remove all ads." }
      ]
    }
  ],
  "subscriptionGroups": [
    {
      "referenceName": "Premium",
      "localizations": [
        { "locale": "en-US", "name": "Premium" }
      ],
      "subscriptions": [
        {
          "productId": "com.example.app.premium.monthly",
          "referenceName": "Premium Monthly",
          "duration": "ONE_MONTH",
          "price": { "baseTerritory": "USA", "baseAmount": "4.99" },
          "localizations": [
            { "locale": "en-US", "name": "Premium Monthly", "description": "Full access for one month." }
          ]
        }
      ]
    }
  ]
}
```

Save the file as `data/iap_packages.json`. See `data/iap_packages.example.json` for the full schema including intro offers, promo offers, and review screenshots.

---

## Supported IAP types

| `type` value | Meaning |
|---|---|
| `CONSUMABLE` | Consumable (e.g. coins, lives) |
| `NON_CONSUMABLE` | Non-consumable (e.g. remove ads, unlock feature) |
| `AUTO_RENEWABLE_SUBSCRIPTION` | Auto-renewable subscription (goes in `subscriptionGroups`) |

---

## Supported subscription durations

`THREE_DAYS`, `ONE_WEEK`, `TWO_WEEKS`, `ONE_MONTH`, `TWO_MONTHS`, `THREE_MONTHS`, `SIX_MONTHS`, `ONE_YEAR`

---

## Step 2: Dry run

```bash
asc --app myapp iap --iap-file data/iap_packages.json --dry-run
```

Validates the JSON structure and shows what would be created/updated without making API calls.

> **Important:** The `--app myapp` flag is **required** on every command unless you've set a default app with `asc app default myapp`. It tells `asc` which app profile (credentials, paths) to use. See [06 Multi-App Profiles](06-multi-app-profiles.md) for details.

---

## Step 3: Upload

```bash
asc --app myapp iap --iap-file data/iap_packages.json
```

Default behavior is **create-only**: existing products are skipped.

---

## Common variants

**Overwrite existing products:**

```bash
asc --app myapp iap --iap-file data/iap_packages.json --update-existing
```

Use this when you need to update prices, localizations, or descriptions on already-created products.

---

## Upload App Store review screenshots

Use `iap-screenshots` to find IAP products that still need App Store review screenshots and upload the missing files:

```bash
asc --app myapp iap-screenshots
```

The command queries App Store Connect online state for all one-time IAP and subscriptions that are missing App Store review screenshots. The optional `data/iap_packages.json` file only prefills `review.screenshot` paths by `productId`; the online App Store Connect state decides which screenshots are missing.

Preview the scan and upload plan without changing App Store Connect:

```bash
asc --app myapp iap-screenshots --dry-run
```

Run non-interactively with paths from your IAP JSON file:

```bash
asc --app myapp iap-screenshots --iap-file data/iap_packages.json --no-prompt --yes
```

In the Web UI, open **IAP 管理 / IAP Management**, go to **补审核截图**, click **扫描缺失**, choose PNG, JPG, or JPEG files for the products that need screenshots, then click **上传截图**. Paths selected in the Web UI are sent only with that upload request and are not written back to `data/iap_packages.json`.

---

## How pricing works

Set `baseTerritory` to Apple’s three-letter territory ID (for example `"USA"` or `"CHN"`) and `baseAmount` (for example `"0.99"`). The tool resolves this to Apple's price point, reads that price point’s equalizations, and creates prices for the equalized territories by default (`"applyEqualizedPrices": true`). Price creation uses Apple’s inline subscription update request by default (`"creationMode": "inlinePatch"`, `"inlineBatchSize": 50`) and falls back to concurrent `subscriptionPrices` POST requests if inline creation is rejected. If Apple returns a price point ID from a previous lookup or error message, you can configure it directly with `pricePointId`.

Common base amounts for USD: `0.99`, `1.99`, `2.99`, `4.99`, `9.99`, `14.99`, `19.99`

---

## FAQ

**A product is skipped even though it doesn't exist**
Check that `productId` matches exactly what's registered in App Store Connect (case-sensitive).

**`IAP 配置为空`**
The JSON file must have at least one item in `items` or one group in `subscriptionGroups`.

**Subscription price not updating**
Use `--update-existing` to overwrite existing price points.

---

## Next steps

- [04 What's New & Store URLs](04-whats-new-and-urls.md)
- [05 Build & Deploy](05-build-and-deploy.md)
