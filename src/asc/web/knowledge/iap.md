# IAP and subscriptions

keywords: IAP 类型 CONSUMABLE NON_CONSUMABLE AUTO_RENEWABLE subscription groupLevel price localization review screenshot iap_packages.json 2-30 45 iap-packages 10选项 infer 会员权益 积分权益

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

## Store pull (this tool)

`pull_remote_snapshot` / Web「从商店导入」copies product identity, type, period, `groupLevel`, localizations, intro summary, and the **base** price only.

It does **not**:

- download review screenshots (local `review.screenshot` stays empty; existing local paths are kept on merge)
- expand Apple's equalized / per-territory price matrix (`applyEqualizedPrices` is recorded as true when a base price exists)

After pull, attach review PNGs and confirm prices before upload.

## Web Agent workflow (`iap-packages` skill)

This Agent does **not** run Ruby skill scripts (`infer_iap_products.rb`, `sync_iap_packages.rb`, `discover_iap_manifest.rb`). Prefer the create-step table infer UI, or edit `iap_packages.json` with `json_patch` / `propose_fix` **after** the user confirms.

### Mode A — product table (preferred)

Need at least `productId` + `name`. Also use price / points / category / displayName when given. Ignore empty rows.

Infer:

| Signal | Result |
| --- | --- |
| ID has `_week_` / `.week.` / `_year_` / `.year.` (or other period) | Auto-renewable subscription |
| ID / name has `super` | Membership + Super tier |
| Category `会员权益` + a period | Membership subscription |
| Category `积分权益`, or coins/credits/pack, **and no** period | Consumable `items[]` |
| ID has `_points_month_` | Credits **subscription** — not `items[]` |
| Cannot tell | `unknown` — ask the user |

Then, in order:

1. Explain `groupLevel` (1 = highest; same level = crossgrade; upgrade immediate/prorated; downgrade next renewal). Batch-confirm **per subscription group**. Never silently write inferred levels. Consumables do not need `groupLevel`.
2. Localization **10 options**, **one category per message**: subscription-group `name` → subscription `name`/`description` → consumable `name`/`description`. Limits: name 2–30; description ≤45. Do not stack all three in one reply.
3. Show a draft (`propose_fix` / dry-run). **Do not write** `iap_packages.json` until groupLevel and localizations are confirmed.
4. Review screenshots may come later: `./iap_review/{price}.PNG` (e.g. `49_99.PNG`). Missing files must not block JSON.

### Mode B — `config.plist` / `.iap-sync.json`

Outside this web Agent. Tell the user to run the `iap-packages` skill on the app repo. Do **not** guess plist paths or copy example manifests.

## Web wizard (create → edit → upload)

The Web UI is a skippable 3-step wizard, not listing-style Local/Diff/Upload tabs.

- **Create**: horizontal tabs — paste a product table (`POST /api/iap/infer`), import from the store, open JSON, blank new, or ask Agent. The JSON file path is chosen only on this step; the label has a `?` help button (`ExampleHelp` kind `iap`). Infer **never** writes `groupLevel` silently — confirm per group (1 = highest; same level = crossgrade). Opening Create pre-fills the last JSON path from form memory (`iap_file`) then profile `paths.iap`; if that file has content, the **Open JSON** tab is selected so the user can skip to Edit; otherwise **Paste table**. Store import (`POST /api/iap/pull` with `write: false`) applies the snapshot in memory and keeps a **sessionStorage** draft keyed by profile + `iapFile`; it does **not** overwrite `iap_packages.json` until the user saves.
- **Edit**: grouped preview list (subscription groups with nested subscriptions, plus one-time IAP). Add/edit opens a dialog with structured fields and localizations. Adding a locale **auto-translates** name/description via `POST /api/iap/translate` (IAP prompt, not What's New release notes). Limits: display name **2–30**, description **≤45**. If no LLM key is configured, the locale row is still added empty and the UI points to Settings. Toolbar: fill missing locales / rewrite name / rewrite description. Store compare (`POST /api/iap/compare`) is **manual** via 核对商店 / Check store — it does **not** run on entering Edit. “用 Agent 细改” opens the right rail with a seed prompt; apply_fix reloads the current item.
- **Upload**: publish plan (create / update / skip). Missing review screenshots stay on this step.

## Skill vs official

`iap-packages` skill:
- `groupLevel` explanation matches Apple (1 highest; same level = crossgrade). **Confirm with the user** — do not silently use inferred levels.
- Localization 10-option UX is a skill workflow, not Apple.
- Skill “group name 2–30” is **not** stated on the official group-name page (see above).
- Skill scripts (`infer_iap_products.rb`, Remote Config `config.plist`) are **outside this web Agent**. Here, edit `iap_packages.json` via propose_fix / json_patch after the user confirms.
