# 01 Install & Project Init

**When to use:** First time setting up `asc` — install the tool, configure an API key, and scaffold your project directory.

---

## Prerequisites

- macOS (build/deploy commands are macOS-only; metadata upload works on Linux/Windows too)
- Python 3.9 or higher
- An app already created in App Store Connect (you need the App ID)

---

## Step 1: Install asc

**Option A — one-line curl install (recommended)**

```bash
source <(curl -fsSL https://raw.githubusercontent.com/yinghuiwang/AppStoreTools/main/install.sh)
```

The `source` prefix makes `asc` available immediately in the current shell.

**Option B — clone and install**

```bash
git clone https://github.com/yinghuiwang/AppStoreTools.git
cd AppStoreTools
bash install.sh
```

**Option C — PyPI**

```bash
pip install asc-appstore-tools
# or latest from GitHub
pip install git+https://github.com/yinghuiwang/AppStoreTools.git
```

Verify:

```bash
asc --version
```

> **Tip:** If you see `asc: command not found`, run `source ~/.zshrc` (or `source ~/.bash_profile` for bash).

---

## Step 2: Create an App Store Connect API Key

1. Open [App Store Connect → Users and Access → Integrations → API Keys](https://appstoreconnect.apple.com/access/integrations/api)
2. Click **+** to create a new key; choose **App Manager** role (or higher)
3. Note the **Issuer ID** and **Key ID**
4. Download the `.p8` private key file (**one-time download only** — save it securely)

---

## Step 3: Get your App ID

Open your app in App Store Connect. The numeric ID appears in the URL:

```
https://appstoreconnect.apple.com/apps/1234567890/...
                                       ^^^^^^^^^^
                                       This is your App ID
```

---

## Step 4: Scaffold the project directory (recommended for Xcode projects)

Run this from your Xcode project root:

```bash
cd /path/to/MyXcodeProject
asc init
```

This creates an `AppStore/` directory tree:

```
AppStore/
├── Config/
│   └── .env          ← fill in your credentials
└── data/
    ├── appstore_info.csv
    ├── screenshots/
    │   ├── cn/
    │   └── en-US/
    └── iap_packages.example.json
```

Edit `AppStore/Config/.env`:

```dotenv
ISSUER_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
KEY_ID=XXXXXXXXXX
KEY_FILE=/path/to/AuthKey_XXXXXXXXXX.p8
APP_ID=1234567890
```

---

## Step 5: Add an app profile

**Option A — import from .env (recommended after `asc init`)**

```bash
asc app import
```

Reads `AppStore/Config/.env` in the current directory and creates the profile automatically.

**Option B — import from a specific path**

```bash
asc app import --path /path/to/MyProject --name myapp
```

**Option C — interactive setup**

```bash
asc app add myapp
```

Follow the prompts to enter Issuer ID, Key ID, .p8 path, App ID, and data paths.

Verify the profile was created:

```bash
asc app list
```

---

## Step 6: Validate the environment

```bash
asc --app myapp check
```

Expected output:

```
✅ Credentials valid
✅ Found editable version: 1.2.0 (PREPARE_FOR_SUBMISSION)
✅ CSV file exists: data/appstore_info.csv
✅ Screenshots directory exists: data/screenshots
```

---

## Set a default app (skip --app on every command)

```bash
asc app default myapp
```

Or add to `.asc/config.toml`:

```toml
[defaults]
default_app = "myapp"
```

---

## FAQ

**`asc: command not found`**
Run `source ~/.zshrc` to reload PATH.

**`❌ Key file not found`**
Check the `.p8` path — tilde expansion (`~/Downloads/AuthKey_...p8`) is supported.

**`asc check` says "no editable App Store version found"**
Create a new version in App Store Connect first (status `PREPARE_FOR_SUBMISSION`). `asc` does not create versions automatically.

**What's the difference between `install.sh`, `asc install`, and `asc init`?**
- `install.sh` — installs the CLI tool itself (Python env + `asc` command)
- `asc install` — guided setup wizard: checks environment and configures an app profile
- `asc init` — scaffolds the `AppStore/` template directory in an Xcode project (run once per project)

---

## Next steps

- [02 Metadata & Screenshots](02-metadata-and-screenshots.md) — fill the CSV and upload content
- [06 Multi-App Profiles](06-multi-app-profiles.md) — manage multiple apps
