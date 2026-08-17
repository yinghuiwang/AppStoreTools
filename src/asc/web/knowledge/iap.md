# IAP and subscriptions

keywords: IAP 类型 CONSUMABLE NON_CONSUMABLE AUTO_RENEWABLE subscription groupLevel price localization review screenshot iap_packages.json 2-30 45

## Official types (4)

| Type | Meaning | JSON `inAppPurchaseType` |
| --- | --- | --- |
| Consumable | Used once, buy again | `CONSUMABLE` |
| Non-Consumable | Buy once, does not expire | `NON_CONSUMABLE` |
| Auto-Renewable Subscription | Renews until cancelled | put under `subscriptionGroups` (not `items`) |
| Non-Renewing Subscription | Fixed duration, no auto-renew | this tool does **not** generate this type |

Source: https://developer.apple.com/help/app-store-connect/reference/in-app-purchases-and-subscriptions/in-app-purchase-types/

## Official field limits

| Field | Limit | Notes |
| --- | --- | --- |
| Product ID | ≤ **100** chars | letters, numbers, `-` `.` `_`; **immutable**; never reused even after delete |
| Reference name | ≤ **64** chars | internal only; editable without review |
| Display name (IAP / subscription) | **2–30** chars | customer-facing; localizable |
| Description | ≤ **45** chars | shown if promoted |
| Review notes | ≤ **4000** chars | reviewers only |
| Promotional image | 1024×1024 JPG/PNG, 72 dpi, RGB, no rounded corners | required to promote IAP |
| Review screenshot | any screenshot size the app supports | **review only**, not on the store; can replace, cannot remove after upload |

Source: https://developer.apple.com/help/app-store-connect/reference/in-app-purchases-and-subscriptions/in-app-purchase-information/

Localized IAP text changes need review; old text stays live until approved.

## Subscription groups (official)

- Users can have **one** active subscription **per group**.
- Up to **100** subscriptions per group.
- **groupLevel / levels**: 1 = highest. Same level = **crossgrade**. Higher level = **upgrade** (immediate, prorated). Lower = **downgrade** (next renewal).
- Same level may hold several durations/prices.
- Durations: 1 week, 1 month, 2 / 3 / 6 months, 1 year. **Duration cannot change after submit.**
- First auto-renewable subscription (and first IAP of each type) must ship **with a new app version**. Later items of that type can submit without a version.

Sources:
- https://developer.apple.com/help/app-store-connect/reference/in-app-purchases-and-subscriptions/auto-renewable-subscription-information
- https://developer.apple.com/help/app-store-connect/manage-subscriptions/offer-auto-renewable-subscriptions
- https://developer.apple.com/help/app-store-connect/manage-submissions-to-app-review/submit-an-in-app-purchase

Group display name: official page forbids control characters / HTML / emoji-like markup. It does **not** publish a 2–30 number. The `iap-packages` skill says group name **2–30**. Treat **2–30 as a conservative target**; IAP/subscription **display name 2–30 is official**.

## `iap_packages.json` (this tool)

Template: packaged `asc/templates/iap_packages.json`.

Top-level:
- `items[]` — one-time IAP (`CONSUMABLE` / `NON_CONSUMABLE`)
- `subscriptionGroups[]` — groups + `subscriptions[]`

One-time item:
- `productId`, `name` (reference), `inAppPurchaseType`
- `availableInAllTerritories`
- `price.baseTerritory` (3-letter **USA** / **CHN**, not `US`), `baseAmount`, optional `applyEqualizedPrices`
- `localizations.<locale>.name` / `.description`
- `review.screenshot` + `review.note`

Subscription group:
- `referenceName` (required)
- `localizations.<locale>.name` (group display name)
- `subscriptions[]`: `productId`, `name`, `subscriptionPeriod` (`ONE_WEEK` / `ONE_MONTH` / `TWO_MONTHS` / `THREE_MONTHS` / `SIX_MONTHS` / `ONE_YEAR`), `groupLevel` (int, 1 = highest), `familySharable`, `price`, `introductoryOffer`, `promotionalOffers`, `review`

Intro offer: `offerMode` `FREE_TRIAL` | `PAY_AS_YOU_GO` | `PAY_UP_FRONT`; `duration`; `numberOfPeriods`; `baseTerritory`.

Price: `pricePointId` **or** `baseTerritory` + `baseAmount`. Territory must be 3 letters (`USA`, not `US`). `applyEqualizedPrices: true` lets Apple convert other storefronts.

## This tool behavior

- Default **create-only**. Existing products/prices/offers/screenshots are skipped unless `--update-existing`.
- Review screenshot path is relative to the JSON file directory (`./iap_review/49_99.PNG`).
- Missing review screenshot can warn; skill workflows may allow generating JSON first and adding PNG later.
- Do not put Credits **subscriptions** (`_points_month_` / period in the ID) into `items[]`.

## Skill vs official

`iap-packages` skill:
- `groupLevel` explanation matches Apple (1 highest; same level = crossgrade). **Confirm with the user** — do not silently use inferred levels.
- Localization 10-option UX is a skill workflow, not Apple.
- Skill “group name 2–30” is **not** stated on the official group-name page (see above).
- Skill scripts (`infer_iap_products.rb`, Remote Config `config.plist`) are **outside this web Agent**. Here, edit `iap_packages.json` via propose_fix / json_patch after the user confirms.
