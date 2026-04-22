# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A Python CLI tool for bulk-uploading App Store Connect metadata (names, subtitles, descriptions, keywords, URLs, screenshots, IAP packages) via the App Store Connect REST API. Entry point is `run.sh`, which wraps `upload_to_appstore.py`.

## Setup

```bash
cp config/.env.example config/.env
# Fill in ISSUER_ID, KEY_ID, KEY_FILE, APP_ID
# Place .p8 private key in config/
pip install -r requirements.txt
```

## Running

```bash
./run.sh                                          # Full upload (metadata + screenshots)
./run.sh --dry-run                                # Preview without uploading
./run.sh metadata                                 # Metadata only
./run.sh keywords                                 # Keywords only
./run.sh screenshots                              # Screenshots only
./run.sh screenshots --display-type APP_IPHONE_67
./run.sh iap --iap-file data/iap_packages.json
./run.sh whats-new --text "Bug fixes."
./run.sh whats-new --file data/whats_new.txt
./run.sh set-support-url --text "https://example.com/support"
./run.sh set-marketing-url --text "https://example.com" --locales en-US
./run.sh set-privacy-policy-url --text "https://example.com/privacy"
./run.sh check                                    # Validate environment only
```

`run.sh` also auto-installs Python 3.9+ via Homebrew/apt/etc. when missing.

## Architecture

All logic lives in `upload_to_appstore.py`. Key components:

- **`AppStoreConnectAPI`** — thin REST client. JWT tokens are auto-refreshed every 15 minutes. Retries on HTTP 429 with `Retry-After`.
- **`upload_metadata()`** — reads `data/appstore_info.csv`, resolves locale codes via `CSV_LOCALE_TO_ASC`, and PATCHes/POSTs `appStoreVersionLocalizations` and `appInfoLocalizations`.
- **`upload_screenshots()`** — walks `data/screenshots/<folder>/`, maps folder names to locales via `SCREENSHOT_FOLDER_TO_LOCALE`, detects device type from pixel dimensions via `DISPLAY_TYPE_BY_SIZE`. Deletes existing screenshots for that device type before re-uploading.
- **`upload_iap()`** — creates or patches IAP products from a JSON file.
- **`upload_whats_new()`** — updates `whatsNew` field on version localizations; supports a plain-text format with `locale:` headers and `---` separators.

`run.sh` maps subcommand names (`metadata`, `keywords`, `screenshots`, etc.) to `--metadata-only`, `--keywords-only`, `--screenshots-only` flags passed to the Python script.

## Data Files

- **`data/appstore_info.csv`** — one row per locale. Required columns: `语言` (locale in `DisplayName(code)` format), `应用名称`, `副标题`, `长描述`, `关键子`. Optional: `技术支持链接`, `营销网站`.
- **`data/screenshots/<locale-folder>/`** — PNG/JPG screenshots; sorted by filename number for upload order.
- **`data/iap_packages.json`** — top-level array or `{ "items": [...] }` object.

## Key Constraints

- App Store Connect must have a version in an editable state (`PREPARE_FOR_SUBMISSION`, `REJECTED`, `IN_REVIEW`, etc.) — the script will not create one.
- Screenshot upload always deletes existing screenshots for the target device type first.
- `config/.env` and `config/*.p8` are git-ignored; never commit real credentials.
