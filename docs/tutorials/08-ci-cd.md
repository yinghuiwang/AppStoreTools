# 08 CI/CD Automation

**When to use:** Automate metadata uploads and app releases in GitHub Actions or other CI/CD pipelines.

---

## Prerequisites

- Completed [01 Install & Project Init](01-install-and-init.md)
- Familiar with [07 Guard Security](07-guard-security.md) (Guard must be disabled in CI)

---

## Core principles

In CI environments:

1. **Create an ephemeral App Profile from secrets** — non-interactive commands still require a resolvable profile; never commit the generated `.toml` or `.p8` file
2. **Disable Guard** (`ASC_GUARD_DISABLE=1`) — CI machines and IPs change on every run
3. **Pass `--app ci` explicitly** — do not rely on an interactive profile picker
4. **Use `--no-interactive` for `build` or `release`** — fail instead of waiting for build input

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

      - name: Configure ephemeral asc profile
        env:
          ASC_ISSUER_ID: ${{ secrets.ASC_ISSUER_ID }}
          ASC_KEY_ID: ${{ secrets.ASC_KEY_ID }}
          ASC_KEY_P8: ${{ secrets.ASC_KEY_P8 }}
          ASC_APP_ID: ${{ secrets.ASC_APP_ID }}
        run: |
          asc_config_dir="$HOME/.config/asc"
          mkdir -p "$asc_config_dir/keys" "$asc_config_dir/profiles"
          printf '%s\n' "$ASC_KEY_P8" > "$asc_config_dir/keys/AuthKey.p8"
          chmod 600 "$asc_config_dir/keys/AuthKey.p8"
          {
            printf '[credentials]\n'
            printf 'issuer_id = "%s"\n' "$ASC_ISSUER_ID"
            printf 'key_id = "%s"\n' "$ASC_KEY_ID"
            printf 'key_file = "%s/keys/AuthKey.p8"\n' "$asc_config_dir"
            printf 'app_id = "%s"\n\n' "$ASC_APP_ID"
            printf '[defaults]\n'
            printf 'csv = "%s/AppStore/data/appstore_info.csv"\n' "$GITHUB_WORKSPACE"
            printf 'screenshots = "%s/AppStore/data/screenshots"\n' "$GITHUB_WORKSPACE"
          } > "$asc_config_dir/profiles/ci.toml"

      - name: Upload metadata
        env:
          ASC_GUARD_DISABLE: "1"
        run: asc --app ci upload --dry-run  # remove --dry-run after validation
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
          PROVISIONING_PROFILE_BASE64: ${{ secrets.PROVISIONING_PROFILE_BASE64 }}
        run: |
          printf '%s' "$CERTIFICATE_P12" | base64 -D > "$RUNNER_TEMP/cert.p12"
          printf '%s' "$PROVISIONING_PROFILE_BASE64" | base64 -D > "$RUNNER_TEMP/AppStore.mobileprovision"
          security cms -D -i "$RUNNER_TEMP/AppStore.mobileprovision" > "$RUNNER_TEMP/profile.plist"
          profile_uuid=$(/usr/libexec/PlistBuddy -c 'Print :UUID' "$RUNNER_TEMP/profile.plist")
          mkdir -p "$HOME/Library/MobileDevice/Provisioning Profiles"
          cp "$RUNNER_TEMP/AppStore.mobileprovision" "$HOME/Library/MobileDevice/Provisioning Profiles/$profile_uuid.mobileprovision"
          security create-keychain -p "" build.keychain
          security import "$RUNNER_TEMP/cert.p12" -k build.keychain -P "$CERTIFICATE_PASSWORD" -T /usr/bin/codesign
          security list-keychains -d user -s build.keychain
          security default-keychain -s build.keychain
          security set-keychain-settings -t 3600 -u build.keychain
          security unlock-keychain -p "" build.keychain
          security set-key-partition-list -S apple-tool:,apple: -s -k "" build.keychain

      - name: Configure ephemeral asc profile
        env:
          ASC_ISSUER_ID: ${{ secrets.ASC_ISSUER_ID }}
          ASC_KEY_ID: ${{ secrets.ASC_KEY_ID }}
          ASC_KEY_P8: ${{ secrets.ASC_KEY_P8 }}
          ASC_APP_ID: ${{ secrets.ASC_APP_ID }}
        run: |
          asc_config_dir="$HOME/.config/asc"
          mkdir -p "$asc_config_dir/keys" "$asc_config_dir/profiles"
          printf '%s\n' "$ASC_KEY_P8" > "$asc_config_dir/keys/AuthKey.p8"
          chmod 600 "$asc_config_dir/keys/AuthKey.p8"
          {
            printf '[credentials]\n'
            printf 'issuer_id = "%s"\n' "$ASC_ISSUER_ID"
            printf 'key_id = "%s"\n' "$ASC_KEY_ID"
            printf 'key_file = "%s/keys/AuthKey.p8"\n' "$asc_config_dir"
            printf 'app_id = "%s"\n' "$ASC_APP_ID"
          } > "$asc_config_dir/profiles/ci.toml"

      - name: Build and upload to TestFlight
        env:
          ASC_GUARD_DISABLE: "1"
        run: |
          asc --app ci release \
            --scheme MyApp \
            --destination testflight \
            --signing manual \
            --profile "$RUNNER_TEMP/AppStore.mobileprovision" \
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
| `PROVISIONING_PROFILE_BASE64` | Base64-encoded App Store `.mobileprovision` file (build scenario only) |

---

## CI environment variable reference

| Variable | Meaning |
|---|---|
| `ASC_ISSUER_ID` | App Store Connect Issuer ID used to generate `ci.toml` |
| `ASC_KEY_ID` | API Key ID used to generate `ci.toml` |
| `ASC_KEY_P8` | Private-key content written to the ephemeral key file |
| `ASC_APP_ID` | Numeric App ID used to generate `ci.toml` |
| `ASC_GUARD_DISABLE` | Set to `1` to disable Guard (required in CI) |
| `ASC_LANG` | UI language (`zh` or `en`) |

---

## FAQ

**How do I store the `.p8` file content securely?**
Paste the full content of the `.p8` file (including `-----BEGIN PRIVATE KEY-----` and `-----END PRIVATE KEY-----`) into a GitHub Secret. The examples write it with `printf` to preserve multiline content without exposing it in logs.

**Metadata upload fails with "no editable version found"**
Ensure App Store Connect has a version in `PREPARE_FOR_SUBMISSION` state, or create one manually before triggering the CI run.

**Build command hangs in CI**
Use the `--no-interactive` flag. This causes the command to fail immediately if input is required, rather than waiting indefinitely.

---

## Next steps

- [07 Guard Security](07-guard-security.md)
- [Back to tutorials index](README.md)
