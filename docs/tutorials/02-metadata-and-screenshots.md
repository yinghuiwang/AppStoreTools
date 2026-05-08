# 02 Metadata & Screenshots

**When to use:** You have credentials configured and want to upload app names, subtitles, descriptions, keywords, and screenshots to App Store Connect.

---

## Prerequisites

- Completed [01 Install & Project Init](01-install-and-init.md)
- An editable app version in App Store Connect (`PREPARE_FOR_SUBMISSION`, `REJECTED`, etc.)

---

## Step 1: Fill in the metadata CSV

Edit `data/appstore_info.csv`. Required columns:

| Column header | Meaning |
|---|---|
| `语言` | Locale in `DisplayName(code)` format, e.g. `简体中文(zh-Hans)` or `English(en-US)` |
| `应用名称` | App name (max 30 chars) |
| `副标题` | Subtitle (max 30 chars) |
| `长描述` | Full description (max 4000 chars) |
| `关键子` | Keywords, comma-separated (max 100 chars total) |

Optional columns:

| Column header | Meaning |
|---|---|
| `技术支持链接` | Support URL |
| `营销网站` | Marketing URL |
| `隐私政策网址` | Privacy policy URL |

Example row:

```
语言,应用名称,副标题,长描述,关键子
English(en-US),My App,The best app,A full description here.,productivity,tools
简体中文(zh-Hans),我的应用,最好的应用,完整描述。,效率,工具
```

---

## Step 2: Prepare screenshots

Place screenshots under `data/screenshots/<locale-folder>/`:

| Folder name | Locale |
|---|---|
| `cn` | `zh-Hans` |
| `en-US` | `en-US` |
| `ja` | `ja` |
| `ko` | `ko` |

Device type is **auto-detected from image dimensions**:

| Display type | Resolution |
|---|---|
| `APP_IPHONE_67` | 1290×2796 or 1320×2868 |
| `APP_IPHONE_65` | 1284×2778 or 1242×2688 |
| `APP_IPHONE_61` | 1179×2556 or 1170×2532 |
| `APP_IPHONE_58` | 1125×2436 |
| `APP_IPHONE_55` | 1242×2208 |
| `APP_IPAD_PRO_3GEN_129` | 2048×2732 |
| `APP_IPAD_PRO_3GEN_11` | 1668×2388 |

Name files with a leading number to control upload order:

```
data/screenshots/en-US/
├── 01_home.png
├── 02_detail.png
└── 03_settings.png
```

---

## Step 3: Dry run first

Always preview before uploading:

```bash
asc --app myapp upload --dry-run
```

This validates credentials, CSV format, and screenshot paths without making any changes.

> **Important:** The `--app myapp` flag is **required** on every command unless you've set a default app with `asc app default myapp`. It tells `asc` which app profile (credentials, paths) to use. See [06 Multi-App Profiles](06-multi-app-profiles.md) for details.

---

## Step 4: Upload everything

```bash
asc --app myapp upload
```

This runs metadata + screenshots in one pass.

---

## Common variants

**Metadata only (no screenshots):**

```bash
asc --app myapp metadata
```

**Keywords only:**

```bash
asc --app myapp keywords
```

**Screenshots only:**

```bash
asc --app myapp screenshots
```

**Screenshots for a specific device type only:**

```bash
asc --app myapp screenshots --display-type APP_IPHONE_67
```

**Use a custom CSV path:**

```bash
asc --app myapp metadata --csv /path/to/custom.csv
```

**Use a custom screenshots directory:**

```bash
asc --app myapp screenshots --screenshots /path/to/custom/screenshots
```

---

## What happens during upload

1. Reads the CSV and resolves locale codes
2. Finds the editable app version via the ASC API
3. Creates or updates each locale's metadata fields
4. For screenshots: deletes existing screenshots for the target device type, then uploads new ones in filename order

> **Note:** Screenshot upload **replaces** all existing screenshots for the same device type. Back up existing screenshots if needed before running.

---

## FAQ

**`❌ 找不到可编辑的 App Store 版本`**
The app version must already exist in App Store Connect with an editable state. Create one manually first.

**Some locales are skipped**
The locale code in the `语言` column must match a locale already added to your app in App Store Connect. Add missing locales there first.

**Screenshot dimensions not recognized**
Check the image size matches one of the supported resolutions in the table above. Export at exactly 1x (no scaling).

---

## Next steps

- [03 IAP & Subscriptions](03-iap-and-subscriptions.md)
- [04 What's New & Store URLs](04-whats-new-and-urls.md)
