# 05 Build & Deploy

**When to use:** Build your Xcode project into an `.ipa` file and upload it to TestFlight or the App Store.

---

## Prerequisites

- Completed [01 Install & Project Init](01-install-and-init.md)
- Xcode project with valid signing certificates and provisioning profiles
- macOS (build/deploy commands are macOS-only)

---

## Step 1: Configure build defaults (optional but recommended)

Edit `.asc/config.toml` in your project root:

```toml
[build]
project = "MyApp.xcworkspace"
scheme = "MyApp"
output = "build"
signing = "auto"
```

- `project`: Path to `.xcodeproj` or `.xcworkspace`
- `scheme`: Xcode scheme name
- `output`: Directory for build artifacts
- `signing`: `"auto"` (auto-detect) or `"manual"` (prompt for certificate/profile)

After this, you can omit `--project` and `--scheme` on every command.

---

## Step 2: Build the app

**First time (interactive, auto-detects project/scheme/signing):**

```bash
asc --app myapp build
```

> **Note:** `asc build` still resolves an App Profile because Guard and cached build settings are profile-aware. You may omit `--app myapp` only after setting a project default with `asc app default myapp`.

**Subsequent runs after setting the project default (uses cached config):**

```bash
asc build
```

**Specify project and scheme explicitly:**

```bash
asc build --project MyApp.xcworkspace --scheme MyApp
```

**Non-interactive mode (fail fast if input needed):**

```bash
asc build --no-interactive
```

**Force interactive mode (even in non-TTY shells):**

```bash
asc build --interactive
```

**Stream full xcodebuild output in real time:**

```bash
asc build --verbose
```

Output artifacts:

```
build/
├── MyApp.xcarchive
├── export/
│   └── MyApp.ipa
├── build.log
└── export.log
```

---

## Step 3: Deploy to TestFlight or App Store

**Upload the .ipa:**

```bash
asc --app myapp deploy --ipa build/export/MyApp.ipa
```

> **Important:** The `--app myapp` flag is **required** here because `asc deploy` needs your App Store Connect credentials to upload the .ipa. See [06 Multi-App Profiles](06-multi-app-profiles.md) for details.

**Specify destination (TestFlight or App Store):**

```bash
asc --app myapp deploy --ipa build/export/MyApp.ipa --destination testflight
asc --app myapp deploy --ipa build/export/MyApp.ipa --destination appstore
```

Currently both destination values use the same `app-store-connect` export method and the same App Store Connect upload path. The option records release intent; final TestFlight testing or App Store submission is selected in App Store Connect.

**Stream upload output:**

```bash
asc --app myapp deploy --ipa build/export/MyApp.ipa --verbose
```

---

## Step 4: Build + Deploy in one command

```bash
asc --app myapp release --scheme MyApp --destination testflight
```

This runs `build` then `deploy` automatically.

As with standalone `deploy`, `release --destination` does not submit a build for App Review; it uploads the build to App Store Connect for the later TestFlight or App Store workflow.

> **Important:** The `--app myapp` flag is **required** because `asc release` needs your App Store Connect credentials for the deploy step.

**With verbose output:**

```bash
asc --app myapp release --scheme MyApp --destination testflight --verbose
```

**Dry run (validate without uploading):**

```bash
asc --app myapp release --scheme MyApp --dry-run
```

---

## Logs and troubleshooting

Build logs are saved to:

- `build/build.log` — xcodebuild archive output
- `build/export.log` — xcodebuild export output
- `build/export/upload.log` — upload output

On failure, the last 20 lines are printed automatically. Use `--verbose` to stream full output in real time.

---

## FAQ

**`❌ 此命令仅支持 macOS`**
Build/deploy commands only work on macOS. Metadata upload works on Linux/Windows.

**An existing archive was not reused**
Archive reuse only happens when the archive in the output directory matches the current bundle ID, marketing version, and build number. Otherwise `asc` creates a new archive; use `--reuse-archive` or `--rebuild` to make the choice explicit.

**Signing certificate not found**
Check that your certificate is installed in Keychain and the provisioning profile is valid. Use `--interactive` to manually select.

**`--verbose` shows nothing**
The subprocess output is being streamed. If it appears stuck, check the log files in `build/`.

---

## Next steps

- [06 Multi-App Profiles](06-multi-app-profiles.md)
- [07 Guard Security](07-guard-security.md)
- [08 CI/CD Automation](08-ci-cd.md)
