# 08 CI/CD Automation

**When to use:** Automate metadata uploads and app releases in GitHub Actions or other CI/CD pipelines.

---

## Prerequisites

- Completed [01 Install & Project Init](01-install-and-init.md)
- Familiar with [07 Guard Security](07-guard-security.md) (Guard must be disabled in CI)

---

## Core principles

In CI environments:
1. **Inject credentials via environment variables** — never commit `.toml` or `.p8` files to the repo
2. **Disable Guard** (`ASC_GUARD_DISABLE=1`) — CI machines and IPs change on every run
3. **Use `--no-interactive`** — prevents commands from waiting for user input

---

## GitHub Actions examples

### Scenario A: Upload metadata + screenshots

```yaml
# .github/workflows/upload-metadata.yml
name: Upload App Store Metadata

on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  upload:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install asc
        run: pip install git+https://github.com/yinghuiwang/AppStoreTools.git

      - name: Write API key file
        run: |
          mkdir -p ~/.config/asc/keys
          echo "${{ secrets.ASC_KEY_P8 }}" > ~/.config/asc/keys/AuthKey.p8
          chmod 600 ~/.config/asc/keys/AuthKey.p8

      - name: Upload metadata
        env:
          ISSUER_ID: ${{ secrets.ASC_ISSUER_ID }}
          KEY_ID: ${{ secrets.ASC_KEY_ID }}
          KEY_FILE: ~/.config/asc/keys/AuthKey.p8
          APP_ID: ${{ secrets.ASC_APP_ID }}
          ASC_GUARD_DISABLE: "1"
        run: asc upload  # add --dry-run first to validate
```

### Scenario B: Build and upload to TestFlight (macOS runner)

```yaml
# .github/workflows/release-testflight.yml
name: Release to TestFlight

on:
  push:
    tags:
      - "v*"

jobs:
  release:
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install asc
        run: pip install git+https://github.com/yinghuiwang/AppStoreTools.git

      - name: Import signing certificate
        env:
          CERTIFICATE_P12: ${{ secrets.CERTIFICATE_P12 }}
          CERTIFICATE_PASSWORD: ${{ secrets.CERTIFICATE_PASSWORD }}
        run: |
          echo "$CERTIFICATE_P12" | base64 --decode > /tmp/cert.p12
          security create-keychain -p "" build.keychain
          security import /tmp/cert.p12 -k build.keychain -P "$CERTIFICATE_PASSWORD" -T /usr/bin/codesign
          security list-keychains -s build.keychain
          security set-keychain-settings -t 3600 -u build.keychain
          security unlock-keychain -p "" build.keychain

      - name: Write API key file
        run: |
          mkdir -p ~/.config/asc/keys
          echo "${{ secrets.ASC_KEY_P8 }}" > ~/.config/asc/keys/AuthKey.p8
          chmod 600 ~/.config/asc/keys/AuthKey.p8

      - name: Build and upload to TestFlight
        env:
          ISSUER_ID: ${{ secrets.ASC_ISSUER_ID }}
          KEY_ID: ${{ secrets.ASC_KEY_ID }}
          KEY_FILE: ~/.config/asc/keys/AuthKey.p8
          APP_ID: ${{ secrets.ASC_APP_ID }}
          ASC_GUARD_DISABLE: "1"
        run: |
          asc release \
            --scheme MyApp \
            --destination testflight \
            --no-interactive \
            --verbose
```

---

## Required GitHub repository secrets

| Secret name | Content |
|---|---|
| `ASC_ISSUER_ID` | App Store Connect Issuer ID |
| `ASC_KEY_ID` | API Key ID |
| `ASC_KEY_P8` | Full content of the `.p8` key file (including `-----BEGIN PRIVATE KEY-----` header/footer) |
| `ASC_APP_ID` | Numeric App ID |
| `CERTIFICATE_P12` | Signing certificate (Base64-encoded `.p12` file, build scenario only) |
| `CERTIFICATE_PASSWORD` | Password for the `.p12` file (build scenario only) |

---

## Environment variable reference

| Variable | Meaning |
|---|---|
| `ISSUER_ID` | App Store Connect Issuer ID |
| `KEY_ID` | API Key ID |
| `KEY_FILE` | Path to the `.p8` private key file |
| `APP_ID` | Numeric App ID |
| `ASC_GUARD_DISABLE` | Set to `1` to disable Guard (required in CI) |
| `ASC_LANG` | UI language (`zh` or `en`) |

---

## FAQ

**How do I store the `.p8` file content securely?**
Paste the full content of the `.p8` file (including `-----BEGIN PRIVATE KEY-----` and `-----END PRIVATE KEY-----`) into a GitHub Secret. In CI, write it to a file with `echo "$SECRET" > file.p8`.

**Metadata upload fails with "no editable version found"**
Ensure App Store Connect has a version in `PREPARE_FOR_SUBMISSION` state, or create one manually before triggering the CI run.

**Build command hangs in CI**
Use the `--no-interactive` flag. This causes the command to fail immediately if input is required, rather than waiting indefinitely.

---

## Next steps

- [07 Guard Security](07-guard-security.md)
- [Back to tutorials index](README.md)
