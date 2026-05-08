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

## How pricing works

Set `baseTerritory` (e.g. `"USA"`) and `baseAmount` (e.g. `"0.99"`). The tool resolves this to Apple's price point and Apple handles cross-territory conversion automatically.

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
