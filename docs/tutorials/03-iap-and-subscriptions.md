# 03 IAP & Subscriptions

**When to use:** You need to create or update In-App Purchases (one-time) or auto-renewable subscriptions in App Store Connect.

---

## Prerequisites

- Completed [01 Install & Project Init](01-install-and-init.md)
- The app already exists in App Store Connect. The command creates missing IAP products, subscription groups, and subscriptions.
- Subscription entries need a PNG/JPG/JPEG review screenshot that exists locally, including during `--dry-run` validation.

---

## Web wizard (Create → Edit → Upload)

Open **IAP** in the Web UI. This is a skippable wizard (Create → Edit → Upload), the same skippable pattern as Listing (Create → Preview → Upload):

1. **Create**: five source tabs (paste table / from store / open JSON / blank new / Agent). The table infers types; **groupLevel must be confirmed per group** (1 = highest, same level = crossgrade) and is never filled silently. If a remembered JSON (or the profile default path) already has content, Create selects the **Open JSON** tab with that path filled so you can skip to Edit; otherwise **Paste table**.
2. **Edit**: a preview list of subscription groups (with nested subscriptions) and one-time IAP. Add / edit opens a dialog for fields and localizations. Adding a locale auto-translates the display name (2–30) and description (≤45). Without an LLM key, the locale row is still added empty and the UI points to Settings.
3. **Upload**: a publish plan only (create / update / skip). Default is create-only; turn on “Update existing items” to PATCH. Missing review screenshots stay on this step.

Unsaved edits do not block changing steps. A real upload saves first if the draft is dirty.

---

---

## Step 1: Create the IAP JSON file

The tool reads either a top-level array of one-time IAP items or an object containing `items`, `subscriptionGroups`, or both.

**One-time IAP only (array):**

```json
[
  {
    "productId": "com.example.app.coins100",
    "inAppPurchaseType": "CONSUMABLE",
    "name": "100 Coins",
    "price": { "baseTerritory": "USA", "baseAmount": "0.99" },
    "localizations": {
      "en-US": { "name": "100 Coins", "description": "Get 100 coins." },
      "zh-Hans": { "name": "100 金币", "description": "获得 100 金币。" }
    }
  }
]
```

**One-time IAP + subscriptions (object):**

```json
{
  "items": [
    {
      "productId": "com.example.app.removeads",
      "inAppPurchaseType": "NON_CONSUMABLE",
      "name": "Remove Ads",
      "price": { "baseTerritory": "USA", "baseAmount": "2.99" },
      "localizations": {
        "en-US": { "name": "Remove Ads", "description": "Remove all ads." }
      }
    }
  ],
  "subscriptionGroups": [
    {
      "referenceName": "Premium",
      "localizations": {
        "en-US": { "name": "Premium" }
      },
      "subscriptions": [
        {
          "productId": "com.example.app.premium.monthly",
          "name": "Premium Monthly",
          "subscriptionPeriod": "ONE_MONTH",
          "groupLevel": 1,
          "price": { "baseTerritory": "USA", "baseAmount": "4.99" },
          "localizations": {
            "en-US": { "name": "Premium Monthly", "description": "Full access for one month." }
          },
          "review": {
            "screenshot": "./iap_review/premium_monthly.png",
            "note": "Describe how the reviewer can access the subscription."
          }
        }
      ]
    }
  ]
}
```

Save the file as `AppStore/data/iap_packages.json`. `asc init` creates a current full template at this path, including intro offers, promo offers, pricing controls, and review screenshots. Relative `review.screenshot` paths are resolved from the JSON file's directory.

---

## Supported IAP types

| `inAppPurchaseType` value | Meaning |
|---|---|
| `CONSUMABLE` | Consumable (e.g. coins, lives) |
| `NON_CONSUMABLE` | Non-consumable (e.g. remove ads, unlock feature) |

Auto-renewable subscriptions go in `subscriptionGroups`; they do not use `inAppPurchaseType`.

---

## Supported subscription durations

`ONE_WEEK`, `ONE_MONTH`, `TWO_MONTHS`, `THREE_MONTHS`, `SIX_MONTHS`, `ONE_YEAR`

---

## Step 2: Dry run

```bash
asc --app myapp iap --iap-file AppStore/data/iap_packages.json --dry-run
```

Validates the JSON and local review-image paths, reads current App Store Connect state, and shows the plan without sending write requests.

> **Important:** The `--app myapp` flag is **required** on every command unless you've set a default app with `asc app default myapp`. It tells `asc` which app profile (credentials, paths) to use. See [06 Multi-App Profiles](06-multi-app-profiles.md) for details.

---

## Step 3: Upload

```bash
asc --app myapp iap --iap-file AppStore/data/iap_packages.json
```

Default behavior creates missing SKUs and missing localizations/prices. Existing names, locales, prices, and review shots stay unchanged unless you pass `--update-existing`. Apple cannot replace an IAP price schedule or availability; those update requests fail instead of reporting success.

---

## Common variants

**Overwrite existing products:**

```bash
asc --app myapp iap --iap-file AppStore/data/iap_packages.json --update-existing
```

Use this when you need to update prices, localizations, or descriptions on already-created products.

---

## Upload App Store review screenshots

Use `iap-screenshots` to find IAP products that still need App Store review screenshots and upload the missing files:

```bash
asc --app myapp iap-screenshots
```

The command queries App Store Connect online state for all one-time IAP and subscriptions that are missing App Store review screenshots. The optional `AppStore/data/iap_packages.json` file only prefills `review.screenshot` paths by `productId`; the online App Store Connect state decides which screenshots are missing.

Preview the scan and upload plan without changing App Store Connect:

```bash
asc --app myapp iap-screenshots --dry-run
```

Run non-interactively with paths from your IAP JSON file:

```bash
asc --app myapp iap-screenshots --iap-file AppStore/data/iap_packages.json --no-prompt --yes
```

In the Web UI, stay on the **Upload** step, expand **Fill review screenshots**, click **Scan missing**, choose PNG, JPG, or JPEG files, then click **Upload screenshots**. Paths selected in the Web UI are sent only with that upload request and are not written back to `AppStore/data/iap_packages.json`.

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
