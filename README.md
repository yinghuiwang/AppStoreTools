# App Store Connect Upload Tool

[中文文档](README.zh-CN.md)

`asc` is an App Store Connect CLI for end-to-end release operations: upload metadata/screenshots/IAP subscriptions, manage localized "What's New" and store URLs, and build/deploy `.ipa` to TestFlight or App Store.

## Quick Start

### Option 1: One-line install via curl (fastest)

```bash
# Download and run installer (using source makes `asc` available immediately)
source <(curl -fsSL https://raw.githubusercontent.com/yinghuiwang/AppStoreTools/main/install.sh)

# Initialize current project
asc install

# Upload metadata + screenshots
asc upload
```

### Option 2: Install from repository

```bash
git clone https://github.com/yinghuiwang/AppStoreTools.git
cd AppStoreTools

# Install environment + CLI
bash install.sh

# Interactive project initialization
asc install

# Start uploading
asc upload
```

### Option 3: Install from PyPI

```bash
pip install asc-appstore-tools
# or latest from GitHub
pip install git+https://github.com/yinghuiwang/AppStoreTools.git

asc install
asc upload
```

## Project Structure

```text
AppStoreTools/
├── src/asc/                        # Python package source
│   ├── commands/                   # CLI subcommands
│   ├── api.py                      # App Store Connect REST client
│   ├── config.py                   # Config management
│   ├── constants.py                # Device/locale mapping
│   └── utils.py                    # Utilities
├── data/                           # Upload input data
│   ├── appstore_info.csv           # Metadata CSV
│   ├── iap_packages.example.json   # IAP/subscription example
│   └── screenshots/                # Screenshots by locale
│       ├── cn/
│       └── en-US/
├── pyproject.toml
└── README.md
```

## Prerequisites

### 1) Create App Store Connect API key

1. Open [App Store Connect - API Keys](https://appstoreconnect.apple.com/access/integrations/api)
2. Create a key with **App Manager** role (or higher)
3. Save **Issuer ID** and **Key ID**
4. Download `.p8` private key (download is one-time only)

### 2) Get App ID

In App Store Connect, open your app and copy the numeric Apple ID from the app URL/info page.

### 3) Add an app profile

**Option A — Scaffold a new project first (recommended for Xcode projects):**

```bash
cd /path/to/MyXcodeProject
asc init                  # creates AppStore/ template structure
# fill in AppStore/Config/.env, then:
asc app import            # reads .env and creates the profile automatically
```

**Option B — Import from an existing project with AppStore/Config/.env:**

```bash
asc app import --path /path/to/MyProject --name myapp
```

**Option C — Interactive setup:**

```bash
asc app add myapp
# Fill in Issuer ID / Key ID / .p8 path / App ID / data paths
```

The key file is copied to `~/.config/asc/keys/`. Profile is saved to `~/.config/asc/profiles/myapp.toml`.

## CSV Format

Expected columns in `data/appstore_info.csv`:

| Column (CN header) | Meaning |
|---|---|
| `语言` | Locale in `DisplayName(code)` format, e.g. `简体中文(zh-Hans)` |
| `应用名称` | App name |
| `副标题` | Subtitle |
| `长描述` | Description |
| `关键子` | Keywords, comma-separated |
| `技术支持链接` | Support URL (optional) |
| `营销网站` | Marketing URL (optional) |

## Screenshot Folder Mapping

Screenshots are read from `data/screenshots/<folder>/`:

| Folder | Locale |
|---|---|
| `cn` | `zh-Hans` |
| `en` | `en-US` |
| `ja` | `ja` |
| `ko` | `ko` |

Screenshots are uploaded in numeric filename order. Device type is detected from image dimensions.

## Usage

```bash
# Install & init
bash install.sh
asc install

# Build / deploy
asc build --scheme MyApp
asc build --project MyApp.xcworkspace --scheme MyApp --destination testflight
asc deploy --ipa build/export/MyApp.ipa
asc release --scheme MyApp --destination testflight
asc release --dry-run

# Metadata / screenshots
asc --app myapp upload
asc --app myapp upload --dry-run
asc --app myapp metadata
asc --app myapp keywords
asc --app myapp screenshots
asc --app myapp screenshots --display-type APP_IPHONE_67

# IAP / subscriptions
asc --app myapp iap --iap-file data/iap_packages.json
asc --app myapp iap --iap-file data/iap_packages.json --update-existing

# What's New
asc --app myapp whats-new --text "Bug fixes and performance improvements."
asc --app myapp whats-new --text "Bug fixes." --locales en-US
asc --app myapp whats-new --file data/whats_new.txt

# URLs
asc --app myapp set-support-url --text "https://example.com/support"
asc --app myapp set-marketing-url --text "https://example.com" --locales en-US
asc --app myapp set-privacy-policy-url --text "https://example.com/privacy"
asc --app myapp support-url
asc --app myapp marketing-url
asc --app myapp privacy-policy-url

# Validation
asc --app myapp check

# Profile management
asc app list
asc app default myapp
asc app show myapp
asc app edit myapp
asc app remove myapp
asc app import                          # import profile from AppStore/Config/.env
asc app import --path /path/to/project --name myapp

# Project scaffold
asc init                                # create AppStore/ template in Xcode project dir
asc init --path /path/to/MyApp

# Guard
asc guard status
asc guard enable
asc guard disable
asc guard unbind --current
asc guard unbind --credential <KEY_ID>
asc guard reset
```

### Updating

```bash
asc update                    # Update to the latest version
asc update --version 0.1.5    # Install a specific version
asc update --branch main      # Install from a specific branch
```

## Build Defaults (`.asc/config.toml`)

```toml
[build]
project = "MyApp.xcworkspace"
scheme = "MyApp"
output = "build"
signing = "auto"
```

Then:

```bash
asc release --destination testflight
```

## Default App Profile (omit `--app`)

```bash
asc app default myapp
```

or manually:

```toml
[defaults]
default_app = "myapp"
```

After that:

```bash
asc upload
asc screenshots
asc check
```

## `whats_new.txt` Format

```text
zh-Hans:
- Fix known issues
- Improve generation speed
---
en-US:
- Bug fixes
- Faster generation
```

## IAP JSON Format

Supported top-level structures:

- `[...]` (one-time IAP only)
- `{ "items": [...] }` (one-time IAP)
- `{ "items": [...], "subscriptionGroups": [...] }` (with subscriptions)

See full schema in `data/iap_packages.example.json`.

## Supported Screenshot Display Types

| Display Type | Resolution |
|---|---|
| `APP_IPHONE_67` | 1290x2796 / 1320x2868 |
| `APP_IPHONE_65` | 1284x2778 / 1242x2688 |
| `APP_IPHONE_61` | 1179x2556 / 1170x2532 |
| `APP_IPHONE_58` | 1125x2436 |
| `APP_IPHONE_55` | 1242x2208 |
| `APP_IPAD_PRO_3GEN_129` | 2048x2732 |
| `APP_IPAD_PRO_3GEN_11` | 1668x2388 |

## Notes

- App Store Connect must already have an editable app version
- Screenshot upload replaces existing screenshots for the same display type
- JWT tokens are auto-refreshed every 15 minutes
- Use `--dry-run` first for safer validation

## FAQ

### `asc: command not found`

```bash
source ~/.zshrc
```

If you use bash:

```bash
source ~/.bash_profile
```

### Difference between `install.sh`, `asc install`, and `asc init`

- `install.sh`: installs the CLI tool itself (Python env + `asc` command)
- `asc install`: interactive guided setup — checks environment and configures app profile
- `asc init`: scaffolds `AppStore/` template directory in an Xcode project (run once per project)

### Version is not editable

This tool does not create versions automatically. Prepare an editable version first in App Store Connect (for example `PREPARE_FOR_SUBMISSION`).
