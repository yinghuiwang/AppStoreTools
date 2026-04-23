# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A pip-installable CLI tool (`asc`) for bulk-uploading App Store Connect metadata (names, subtitles, descriptions, keywords, URLs, screenshots, IAP packages, and subscriptions) via the App Store Connect REST API.

## Setup

```bash
pip install -e ".[dev]"
asc app add myapp   # interactive credential setup
```

## Running

```bash
asc --app myapp upload                                    # Full upload (metadata + screenshots)
asc --app myapp upload --dry-run                          # Preview without uploading
asc --app myapp metadata                                  # Metadata only
asc --app myapp keywords                                  # Keywords only
asc --app myapp screenshots                               # Screenshots only
asc --app myapp screenshots --display-type APP_IPHONE_67
asc --app myapp iap --iap-file data/iap_packages.json    # IAP + Subscriptions (create-only)
asc --app myapp iap --iap-file data/iap_packages.json --update-existing  # Overwrite existing
asc --app myapp iap --iap-file data/iap_packages.json --dry-run
asc --app myapp whats-new --text "Bug fixes."
asc --app myapp whats-new --file data/whats_new.txt
asc --app myapp set-support-url --text "https://example.com/support"
asc --app myapp set-marketing-url --text "https://example.com" --locales en-US
asc --app myapp set-privacy-policy-url --text "https://example.com/privacy"
asc --app myapp check                                     # Validate environment only
asc build --scheme MyApp                                  # Build .xcarchive + export .ipa
asc deploy --ipa build/export/MyApp.ipa                  # Upload .ipa to TestFlight/App Store
asc release --scheme MyApp --destination testflight      # Build + upload in one step
asc app list
asc app remove myapp
```

Create `.asc/config.toml` with `default_app = "myapp"` to omit `--app` on every command.

## Architecture

Source lives in `src/asc/`. Key modules:

- **`api.py`** — `AppStoreConnectAPI` thin REST client. JWT tokens are auto-refreshed every 15 minutes. Retries on HTTP 429 with `Retry-After`.
- **`config.py`** — `Config` class with priority chain: CLI args > local `.asc/config.toml` > global `~/.config/asc/profiles/<name>.toml` > env vars.
- **`constants.py`** — `DISPLAY_TYPE_BY_SIZE`, `SCREENSHOT_FOLDER_TO_LOCALE`, `CSV_LOCALE_TO_ASC`, `normalize_locale_code()`.
- **`utils.py`** — `parse_csv()`, `resolve_locale()`, `make_api_from_config()`.
- **`commands/metadata.py`** — `_upload_metadata_core()`, all metadata subcommands.
- **`commands/screenshots.py`** — `_upload_screenshots_core()`, device-type detection from image dimensions.
- **`commands/iap.py`** — IAP create/patch from JSON file, with subscriptionGroups support.
- **`commands/subscriptions.py`** — subscription bulk upload: groups, subscriptions, localizations, prices, intro/promo offers, review screenshots.
- **`commands/whats_new.py`** — `whatsNew` field update with multi-locale file format.
- **`commands/app_config.py`** — `asc app add/list/remove` profile management.
- **`commands/build.py`** — `build_core()`, `deploy_core()`, `upload_ipa()`; `asc build/deploy/release` subcommands.
- **`cli.py`** — typer app wiring all subcommands.

## Data Files

- **`data/appstore_info.csv`** — one row per locale. Required columns: `语言` (locale in `DisplayName(code)` format), `应用名称`, `副标题`, `长描述`, `关键子`. Optional: `技术支持链接`, `营销网站`.
- **`data/screenshots/<locale-folder>/`** — PNG/JPG screenshots; sorted by filename number for upload order.
- **`data/iap_packages.json`** — top-level array, `{"items": [...]}`, or combined with `{"subscriptionGroups": [...]}`. Supports both one-time IAP and auto-renewable subscriptions. See `data/iap_packages.example.json` for the full schema.

## Key Constraints

- App Store Connect must have a version in an editable state (`PREPARE_FOR_SUBMISSION`, `REJECTED`, `IN_REVIEW`, etc.) — the tool will not create one.
- Screenshot upload always deletes existing screenshots for the target device type first.
- Subscriptions: default behavior is create-only (existing groups/subscriptions/prices/offers/screenshots are skipped). Use `--update-existing` to overwrite.
- Subscription prices use `baseTerritory` + `baseAmount`; tool resolves to Apple Price Point and relies on Apple's automatic cross-territory conversion.
- Credentials stored in `~/.config/asc/profiles/<name>.toml` and `~/.config/asc/keys/`. Never commit real credentials.

## Publishing

Tag a release to trigger auto-publish to PyPI:

```bash
git tag v0.1.0 && git push origin v0.1.0
```

Requires `PYPI_API_TOKEN` secret in GitHub repository settings.
