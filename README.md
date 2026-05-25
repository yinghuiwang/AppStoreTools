# App Store Connect Upload Tool

[中文文档](README.zh-CN.md) | [Tutorials](docs/tutorials/README.md)

`asc` is a Python CLI for App Store Connect release work. It can upload localized metadata and screenshots, create or update IAP and subscriptions, manage "What's New" text and store URLs, build Xcode projects, upload `.ipa` files, and run a local Web UI for common workflows.

## Features

- Metadata upload from `data/appstore_info.csv`
- Screenshot upload by locale and device size, with automatic display type detection
- IAP and auto-renewable subscription sync from JSON
- Release notes and support / marketing / privacy policy URL updates
- Xcode archive, IPA export, and App Store Connect upload
- Multi-app profiles with local defaults
- Guard checks for machine / IP / credential binding before risky operations
- Local Web UI via `asc web`

## Tutorials

Step-by-step guides for every major workflow:

| # | Tutorial | Topic |
|---|----------|-------|
| 01 | [Install & Project Init](docs/tutorials/01-install-and-init.md) | Install `asc`, create API key, scaffold project, add app profile |
| 02 | [Metadata & Screenshots](docs/tutorials/02-metadata-and-screenshots.md) | Fill CSV, name screenshot folders, run `upload` / `metadata` / `screenshots` |
| 03 | [IAP & Subscriptions](docs/tutorials/03-iap-and-subscriptions.md) | Structure `iap_packages.json`, upload one-time IAP and subscriptions |
| 04 | [What's New & Store URLs](docs/tutorials/04-whats-new-and-urls.md) | Update release notes and support / marketing / privacy URLs |
| 05 | [Build & Deploy](docs/tutorials/05-build-and-deploy.md) | `asc build`, `asc deploy`, `asc release`, TestFlight vs App Store |
| 06 | [Multi-App Profiles](docs/tutorials/06-multi-app-profiles.md) | Manage multiple apps, set a default, switch between projects |
| 07 | [Guard Security](docs/tutorials/07-guard-security.md) | Machine / IP / credential binding, conflict resolution, CI bypass |
| 08 | [CI/CD Automation](docs/tutorials/08-ci-cd.md) | GitHub Actions example, inject credentials via env vars |

## Quick Start

### Option 1: Install via curl

```bash
curl -fL --retry 5 --connect-timeout 20 \
  -o /tmp/asc-install.sh \
  https://raw.githubusercontent.com/yinghuiwang/AppStoreTools/main/install.sh
bash /tmp/asc-install.sh
```

Install a specific branch for testing:

```bash
curl -fL --retry 5 --connect-timeout 20 \
  -o /tmp/asc-install.sh \
  https://raw.githubusercontent.com/yinghuiwang/AppStoreTools/main/install.sh
bash /tmp/asc-install.sh --branch feat/web-build-interactive-release-options
```

### Option 2: Install from repository

```bash
git clone https://github.com/yinghuiwang/AppStoreTools.git
cd AppStoreTools
bash install.sh
asc install
asc upload --dry-run
```

### Option 3: Install from PyPI or GitHub

```bash
pip install asc-appstore-tools
# or latest from GitHub
pip install git+https://github.com/yinghuiwang/AppStoreTools.git

asc install
asc upload --dry-run
```

For local development:

```bash
pip install -e ".[dev]"
pytest
```

## Prerequisites

1. Create an App Store Connect API key in [Users and Access > Integrations](https://appstoreconnect.apple.com/access/integrations/api).
2. Use the **App Manager** role or higher.
3. Save the **Issuer ID** and **Key ID**.
4. Download the `.p8` private key. Apple only allows downloading it once.
5. Copy the numeric Apple ID for your app from App Store Connect.

## Project Setup

### Scaffold a new project

```bash
cd /path/to/MyXcodeProject
asc init
# Fill AppStore/Config/.env, then:
asc app import
```

### Import an existing AppStore/Config/.env

```bash
asc app import --path /path/to/MyProject --name myapp
```

### Configure interactively

```bash
asc app add myapp
```

The private key is copied to `~/.config/asc/keys/`. Profiles are saved under `~/.config/asc/profiles/`.

## Project Structure

```text
AppStoreTools/
├── src/asc/                        # Python package source
│   ├── commands/                   # CLI subcommands
│   ├── web/                        # Local Web UI
│   ├── api.py                      # App Store Connect REST client
│   ├── config.py                   # Config management
│   └── i18n.py                     # Chinese / English CLI text
├── data/                           # Example upload data
│   ├── appstore_info.csv           # Metadata CSV
│   ├── iap_packages.example.json   # IAP/subscription example
│   └── screenshots/                # Screenshots by locale
├── docs/tutorials/                 # Workflow tutorials
├── tests/                          # pytest suite
└── pyproject.toml
```

## CSV Format

Expected columns in `data/appstore_info.csv`:

| Column | Meaning |
|---|---|
| `语言` | Locale in `DisplayName(code)` format, for example `简体中文(zh-Hans)` |
| `应用名称` | App name |
| `副标题` | Subtitle |
| `长描述` | Description |
| `关键子` | Keywords, comma-separated |
| `技术支持链接` | Support URL, optional |
| `营销网站` | Marketing URL, optional |

## Screenshot Folders

Screenshots are read from `data/screenshots/<folder>/`:

| Folder | Locale |
|---|---|
| `cn` | `zh-Hans` |
| `en` | `en-US` |
| `ja` | `ja` |
| `ko` | `ko` |

Files are uploaded in numeric filename order. Device type is detected from image dimensions; use `--display-type` to upload only one device family.

## Command Reference

```bash
# Help / version
asc --help
asc -h
asc --version

# Guided setup and project templates
asc install
asc init
asc init --path /path/to/MyApp

# App profiles
asc app add myapp
asc app import
asc app import --path /path/to/project --name myapp
asc app list
asc app default myapp
asc app show myapp
asc app edit myapp
asc app remove myapp

# Metadata and screenshots
asc --app myapp upload
asc --app myapp upload --dry-run
asc --app myapp metadata
asc --app myapp keywords
asc --app myapp screenshots
asc --app myapp screenshots --display-type APP_IPHONE_67
asc --app myapp check

# IAP and subscriptions
asc --app myapp iap --iap-file data/iap_packages.json
asc --app myapp iap --iap-file data/iap_packages.json --update-existing

# What's New
asc --app myapp whats-new --text "Bug fixes and performance improvements."
asc --app myapp whats-new --text "Bug fixes." --locales en-US
asc --app myapp whats-new --file data/whats_new.txt

# Store URLs
asc --app myapp set-support-url --text "https://example.com/support"
asc --app myapp set-marketing-url --text "https://example.com" --locales en-US
asc --app myapp set-privacy-policy-url --text "https://example.com/privacy"
asc --app myapp support-url
asc --app myapp marketing-url
asc --app myapp privacy-policy-url

# Build and deploy
asc build
asc build --project MyApp.xcworkspace --scheme MyApp
asc build --signing manual --profile path/to/profile.mobileprovision --certificate "Apple Distribution: ACME"
asc build --no-interactive --dry-run
asc --app myapp deploy --ipa build/export/MyApp.ipa
asc --app myapp release --destination testflight
asc --app myapp release --destination appstore --reuse-archive

# Local Web UI
asc web
asc web --port 9090
asc web --foreground
asc web status
asc web stop
asc web --host 0.0.0.0 --no-open

# Guard
asc guard status
asc guard enable
asc guard disable
asc guard unbind --current
asc guard unbind --credential <KEY_ID>
asc guard reset

# Maintenance
asc update
asc update --version 0.1.12
asc update --branch main
asc uninstall
```

## Build Defaults

Build settings can be stored in local `.asc/config.toml`:

```toml
[build]
project = "MyApp.xcworkspace"
scheme = "MyApp"
bundle_id = "com.example.myapp"
output = "build"
signing = "auto"
certificate = "Apple Distribution: Example Inc."
profile = "/path/to/profile.mobileprovision"
destination = "testflight"
```

`asc build` and `asc release` can auto-detect the project, scheme, bundle ID, signing certificates, and provisioning profiles. Resolved values are cached in `.asc/config.toml` for later runs.

## Default App Profile

Set a default profile to omit `--app`:

```bash
asc app default myapp
```

or write it manually:

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

## Configuration and Security

- Global profiles live in `~/.config/asc/profiles/`.
- Private keys are copied to `~/.config/asc/keys/`.
- Local project config lives in `.asc/config.toml`.
- Never commit `.p8` keys, `.env` files, local profiles, or generated credentials.
- Run `--dry-run` before commands that modify metadata, screenshots, IAP, subscriptions, or release state.
- Build and deploy require macOS and Xcode command line tools; metadata operations can run on Linux or Windows.

## Troubleshooting

If `asc` is not found after install:

```bash
source ~/.zshrc
# or
source ~/.bash_profile
```

If `asc check` reports no editable version, create an App Store version in App Store Connect first. The version must be in an editable state such as `PREPARE_FOR_SUBMISSION`.
