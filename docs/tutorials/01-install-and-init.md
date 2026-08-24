# 01 Install & Project Init

**When to use:** First time setting up `asc` — install the tool, configure an API key, and scaffold your project directory.

---

## Prerequisites

- macOS (build/deploy commands are macOS-only; metadata upload works on Linux/Windows too)
- Python 3.9 or higher
- An app already created in App Store Connect (you need the App ID)

---

## Step 1: Install asc

**Option A — PyPI (recommended)**

```bash
pip install asc-appstore-tools
# or: pipx install asc-appstore-tools
```

Windows uses the same PyPI command. `install.sh` is macOS / Linux only.

**Option B — one-line curl install (macOS / Linux)**

Installs from PyPI by default; falls back to GitHub if PyPI is unreachable.

```bash
curl -fsSL https://raw.githubusercontent.com/yinghuiwang/AppStoreTools/main/install.sh | bash
```

Install a specific GitHub branch for testing:

```bash
asc_install_ref=your-branch-or-tag
curl -fsSL https://raw.githubusercontent.com/yinghuiwang/AppStoreTools/main/install.sh | bash -s -- --ref "$asc_install_ref"
```

**Option C — clone and install**

```bash
git clone https://github.com/yinghuiwang/AppStoreTools.git
cd AppStoreTools
bash install.sh
```

Verify:

```bash
asc --version
```

> **Tip:** If you see `asc: command not found`, run `source ~/.zshrc` (or `source ~/.bash_profile` for bash).

Uninstall:

```bash
asc uninstall --yes
# or: pip uninstall asc-appstore-tools
# or: pipx uninstall asc-appstore-tools
```

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
│   ├── .env.example  ← copy to .env and fill in your credentials
│   └── .gitignore    ← keeps .env out of git
└── data/
    ├── appstore_info.csv
    ├── screenshots/
    ├── iap_packages.json
    └── iap_review/
        └── premium_monthly.png
```

Create the local credential file, then edit it:

```bash
cp AppStore/Config/.env.example AppStore/Config/.env
```

`AppStore/Config/.env`:

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
asc app import --name myapp
```

Reads `AppStore/Config/.env` in the current directory and creates the `myapp` profile automatically. Without `--name`, the project directory name is used.

**Option B — import from a specific path**

```bash
asc app import --path /path/to/MyProject --name myapp
```

**Option C — interactive setup**

```bash
asc app add myapp
```

Follow the prompts to enter Issuer ID, Key ID, .p8 path, and App ID. CSV and screenshot paths are filled later, when you upload.

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
✅ CSV file exists: /path/to/MyXcodeProject/AppStore/data/appstore_info.csv
✅ Screenshots directory exists: /path/to/MyXcodeProject/AppStore/data/screenshots
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
