# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A pip-installable CLI tool (`asc`) for bulk-uploading App Store Connect metadata (names, subtitles, descriptions, keywords, URLs, screenshots, IAP packages, and subscriptions) via the App Store Connect REST API.

**Key Features:**
- 🔐 JWT authentication with auto-refresh (15-minute tokens)
- 🛡️ Security guard system (machine/IP/credential binding)
- 🌍 Internationalization (Chinese/English)
- 📦 4-level configuration priority system
- 🔄 Automatic retry with rate limit handling (HTTP 429)
- 🏗️ Build and deploy support (xcodebuild + TestFlight/App Store)

## Setup

```bash
# Install from source
pip install -e ".[dev]"

# Or install from GitHub
pip install git+https://github.com/yinghuiwang/AppStoreTools.git

# Quick setup with install script
source <(curl -fsSL https://raw.githubusercontent.com/yinghuiwang/AppStoreTools/main/install.sh)

# Initialize project
asc install              # Interactive setup wizard
asc init                 # Scaffold AppStore/ directory in Xcode project

# Add app configuration
asc app add myapp        # Interactive credential setup
```

## Running

```bash
# Metadata commands
asc --app myapp upload                                    # Full upload (metadata + screenshots)
asc --app myapp upload --dry-run                          # Preview without uploading
asc --app myapp metadata                                  # Metadata only
asc --app myapp keywords                                  # Keywords only
asc --app myapp check                                     # Validate environment only

# Screenshot commands
asc --app myapp screenshots                               # Upload all screenshots
asc --app myapp screenshots --display-type APP_IPHONE_67  # Upload specific device type

# IAP and Subscription commands
asc --app myapp iap --iap-file data/iap_packages.json                    # IAP + Subscriptions (create-only)
asc --app myapp iap --iap-file data/iap_packages.json --update-existing  # Overwrite existing
asc --app myapp iap --iap-file data/iap_packages.json --dry-run          # Preview only

# What's New commands
asc --app myapp whats-new --text "Bug fixes."
asc --app myapp whats-new --file data/whats_new.txt

# URL commands
asc --app myapp set-support-url --text "https://example.com/support"
asc --app myapp set-marketing-url --text "https://example.com" --locales en-US
asc --app myapp set-privacy-policy-url --text "https://example.com/privacy"

# Build and Deploy commands
asc build --scheme MyApp                                  # Build .xcarchive + export .ipa
asc deploy --ipa build/export/MyApp.ipa                   # Upload .ipa to TestFlight/App Store
asc release --scheme MyApp --destination testflight       # Build + upload in one step

# Guard commands
asc guard status                                          # 查看绑定状态
asc guard enable                                          # 启用守卫
asc guard disable                                         # 禁用守卫
asc guard unbind --current                                # 解除当前环境绑定
asc guard reset                                           # 清除所有绑定

# App configuration commands
asc app list                                              # List all app profiles
asc app show myapp                                        # Show app details
asc app add myapp                                         # Add new app profile
asc app edit myapp                                        # Edit app profile
asc app remove myapp                                      # Remove app profile
asc app default myapp                                     # Set default app
asc app import myapp                                      # Import from AppStore/Config/.env
```

**Tip:** Create `.asc/config.toml` with `default_app = "myapp"` to omit `--app` on every command.

## Architecture

**See [ARCHITECTURE.md](ARCHITECTURE.md) for comprehensive technical documentation.**

Source lives in `src/asc/`. Key modules:

### Core Layer
- **`api.py`** (720 lines) — `AppStoreConnectAPI` REST client. JWT tokens auto-refresh every 15 minutes. Retries on HTTP 429 with `Retry-After`. Handles all ASC REST API endpoints.
- **`config.py`** (194 lines) — `Config` class with 4-level priority chain: CLI args > local `.asc/config.toml` > global `~/.config/asc/profiles/<name>.toml` > env vars.
- **`guard.py`** (168 lines) — `Guard` security system with machine/IP/credential binding. Prevents credential abuse. Storage: `~/.config/asc/guard.json`. Default enabled, disable via `asc guard disable` or `ASC_GUARD_DISABLE=1`.
- **`utils.py`** — `parse_csv()`, `resolve_locale()`, `make_api_from_config()`, `md5_of_file()`.
- **`i18n.py`** (376 lines) — Internationalization support (Chinese/English). `t()` translation function, `get_system_language()`.
- **`constants.py`** — `DISPLAY_TYPE_BY_SIZE`, `SCREENSHOT_FOLDER_TO_LOCALE`, `CSV_LOCALE_TO_ASC`, `normalize_locale_code()`.

### Command Layer (`commands/`)
- **`metadata.py`** (692 lines) — `_upload_metadata_core()`, all metadata subcommands (upload, keywords, URLs, check).
- **`screenshots.py`** (252 lines) — `_upload_screenshots_core()`, device-type detection from image dimensions.
- **`iap.py`** (245 lines) — IAP create/patch from JSON file, supports consumable/non-consumable/subscriptions.
- **`subscriptions.py`** (533 lines) — Subscription bulk upload: groups, subscriptions, localizations, prices, intro/promo offers, review screenshots.
- **`whats_new.py`** (190 lines) — `whatsNew` field update with multi-locale file format.
- **`build.py`** (443 lines) — `build_core()`, `deploy_core()`, `upload_ipa()`; `asc build/deploy/release` subcommands.
- **`app_config.py`** (617 lines) — `asc app add/list/show/edit/remove/default/import` profile management.
- **`guard_cmd.py`** (114 lines) — `asc guard` subcommands (`status`, `enable`, `disable`, `unbind`, `reset`).

### CLI Layer
- **`cli.py`** — Typer app wiring all subcommands. Routes commands to appropriate handlers.

## Data Files

- **`data/appstore_info.csv`** — One row per locale. Required columns: `语言` (locale in `DisplayName(code)` format), `应用名称`, `副标题`, `长描述`, `关键子`. Optional: `技术支持链接`, `营销网站`, `隐私政策网址`.
- **`data/screenshots/<locale-folder>/`** — PNG/JPG screenshots; sorted by filename number for upload order. Supported device types:
  - iPhone: 6.7", 6.5", 5.5"
  - iPad: Pro 12.9", Pro 11"
  - Apple Watch
- **`data/iap_packages.json`** — Top-level array, `{"items": [...]}`, or combined with `{"subscriptionGroups": [...]}`. Supports:
  - One-time IAP (CONSUMABLE, NON_CONSUMABLE)
  - Auto-renewable subscriptions (AUTO_RENEWABLE_SUBSCRIPTION)
  - Subscription groups, localizations, prices, intro/promo offers
  - See `src/asc/templates/iap_packages.json` for full schema

## Configuration Files

### Local Project Config (`.asc/config.toml`)
```toml
[credentials]
issuer_id = "..."
key_id = "..."
key_file = "..."
app_id = "..."

[defaults]
csv = "data/appstore_info.csv"
screenshots = "data/screenshots"
default_app = "myapp"

[build]
project = "MyApp.xcodeproj"
scheme = "MyApp"
output = "build"
signing = "auto"
```

### Global App Profile (`~/.config/asc/profiles/<name>.toml`)
Same structure as local config, but stored globally for reuse across projects.

### Environment Variables
- `ISSUER_ID`, `KEY_ID`, `KEY_FILE`, `APP_ID` — Credentials
- `ASC_LANG` — Language (zh/en)
- `ASC_GUARD_DISABLE=1` — Disable security guard

## Key Constraints

- **Version State**: App Store Connect must have a version in an editable state (`PREPARE_FOR_SUBMISSION`, `REJECTED`, `IN_REVIEW`, etc.) — the tool will not create one.
- **Screenshot Upload**: Always deletes existing screenshots for the target device type first before uploading new ones.
- **Subscriptions**: Default behavior is create-only (existing groups/subscriptions/prices/offers/screenshots are skipped). Use `--update-existing` to overwrite.
- **Subscription Prices**: Use `baseTerritory` + `baseAmount`; tool resolves to Apple Price Point and relies on Apple's automatic cross-territory conversion.
- **Credentials**: Stored in `~/.config/asc/profiles/<name>.toml` and `~/.config/asc/keys/`. Never commit real credentials.
- **Guard System**: Default enabled. Binds credentials to machine/IP. Disable via `asc guard disable` or `ASC_GUARD_DISABLE=1` for CI/CD environments.

## Security Features

### Guard System
- **Machine Binding**: macOS uses IOPlatformUUID, others use platform.node() + uuid.getnode()
- **IP Binding**: Public IP from api.ipify.org or ifconfig.me
- **Credential Binding**: Key ID binding
- **Storage**: `~/.config/asc/guard.json`
- **Conflict Detection**: Warns when same credential used on different machine/IP

## Development

### Project Structure
```
src/asc/
├── __init__.py           # Version: 0.1.0
├── __main__.py           # Entry point
├── cli.py                # Typer CLI app
├── api.py                # ASC REST API client (720 lines)
├── config.py             # Configuration system (194 lines)
├── guard.py              # Security guard (168 lines)
├── utils.py              # Utility functions
├── i18n.py               # Internationalization (376 lines)
├── constants.py          # Constants and mappings
├── commands/             # Command modules
│   ├── metadata.py       # (692 lines)
│   ├── screenshots.py    # (252 lines)
│   ├── iap.py            # (245 lines)
│   ├── subscriptions.py  # (533 lines)
│   ├── whats_new.py      # (190 lines)
│   ├── build.py          # (443 lines)
│   ├── app_config.py     # (617 lines)
│   └── guard_cmd.py      # (114 lines)
└── templates/            # Template files
    ├── iap_packages.json
    └── iap_review/
```

### Testing
```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests (when available)
pytest

# Type checking
mypy src/asc

# Linting
ruff check src/asc
```

### Dependencies
- **typer>=0.12.0** — CLI framework
- **PyJWT>=2.8.0** — JWT authentication
- **cryptography>=41.0.0** — Encryption library
- **requests>=2.31.0** — HTTP client
- **Pillow>=10.0.0** — Image processing
- **python-dotenv>=1.0.0** — .env file support
- **tomli>=2.0.0** — TOML parsing (Python <3.11)

**Python Support**: 3.9, 3.10, 3.11, 3.12

## Publishing

Tag a release to trigger auto-publish to PyPI:

```bash
git tag v0.1.0 && git push origin v0.1.0
```

Requires `PYPI_API_TOKEN` secret in GitHub repository settings.
