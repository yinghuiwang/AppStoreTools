# 06 Multi-App Profiles

**When to use:** Manage multiple apps or switch between different App Store Connect credentials.

---

## Prerequisites

- Completed [01 Install & Project Init](01-install-and-init.md)

---

## Step 1: List all profiles

```bash
asc app list
```

Shows all configured app profiles with their locations.

---

## Step 2: Add a new app profile

```bash
asc app add production-app
```

Follow the prompts to enter credentials and data paths. The profile is saved to `~/.config/asc/profiles/production-app.toml`.

---

## Step 3: View profile details

```bash
asc app show production-app
```

Displays the full configuration for a profile.

---

## Step 4: Edit a profile

```bash
asc app edit production-app
```

Interactively update credentials, paths, or other settings.

---

## Step 5: Set a default app

```bash
asc app default production-app
```

After this, you can omit `--app` on all commands:

```bash
asc upload              # uses production-app
asc screenshots         # uses production-app
asc build               # uses production-app
```

To see which app is currently default:

```bash
asc app list
```

The default is marked with a `*`.

---

## Step 6: Switch between apps

Use `--app` to override the default:

```bash
asc --app staging-app upload
asc --app staging-app screenshots
```

---

## Step 7: Remove a profile

```bash
asc app remove old-app
```

This deletes the profile from `~/.config/asc/profiles/` but does not affect the `.p8` key file.

---

## Profile storage

- **Global profiles:** `~/.config/asc/profiles/<name>.toml`
- **API keys:** `~/.config/asc/keys/` (copied from your original location)
- **Local project config:** `.asc/config.toml` (optional, overrides global)

---

## Local project config (`.asc/config.toml`)

You can also store app-specific settings in your project:

```toml
[defaults]
default_app = "myapp"

[build]
project = "MyApp.xcworkspace"
scheme = "MyApp"
output = "build"
signing = "auto"
```

This takes precedence over global profiles for the current project.

---

## FAQ

**Can I have different CSV/screenshots paths per app?**
Yes. Each profile stores its own `csv` and `screenshots` paths. Set them when adding the profile or edit them later with `asc app edit`.

**Where are my credentials stored?**
Profiles are in `~/.config/asc/profiles/` (readable TOML). API keys are in `~/.config/asc/keys/` (the `.p8` files). Never commit these to git.

**Can I import a profile from another machine?**
Yes. Copy the `.toml` file from `~/.config/asc/profiles/` and the corresponding `.p8` key from `~/.config/asc/keys/` to the same locations on the new machine.

---

## Next steps

- [07 Guard Security](07-guard-security.md)
- [02 Metadata & Screenshots](02-metadata-and-screenshots.md)
