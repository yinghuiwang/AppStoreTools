# App Profile Show & Edit Design

Date: 2026-04-23

## Overview

Add two new subcommands to `asc app`: `show` and `edit`.

- `asc app show <name>` — display all fields of a named profile
- `asc app edit <name>` — re-prompt all fields with current values as defaults, then overwrite the profile

## Commands

### `asc app show <name>`

Reads `~/.config/asc/profiles/<name>.toml` and prints all fields:

```
App profile: myapp
  Issuer ID:        abc-123-...
  Key ID:           ABCD1234
  Key file:         ~/.config/asc/keys/AuthKey_ABCD1234.p8
  App ID:           1234567890
  CSV path:         data/appstore_info.csv
  Screenshots path: data/screenshots
```

Error if profile does not exist.

### `asc app edit <name>`

1. Load existing profile via `config.get_app_profile(name)` → dict of current values
2. Prompt each field with current value as default (user presses Enter to keep)
3. Key file: if user enters a new path, copy it to `~/.config/asc/keys/`; if unchanged, skip copy
4. Call `config.save_app_profile()` to overwrite the profile file
5. Print confirmation

## Files Changed

| File | Change |
|------|--------|
| `src/asc/config.py` | Add `get_app_profile(name) -> dict` |
| `src/asc/commands/app_config.py` | Add `cmd_app_show`, `cmd_app_edit` |
| `src/asc/cli.py` | Register `show` and `edit` under `app_cmd` |

## `config.get_app_profile(name)`

Returns a dict with keys: `issuer_id`, `key_id`, `key_file`, `app_id`, `csv`, `screenshots`.
Returns `None` if the profile file does not exist.

## Error Cases

- Profile not found: print error and exit with code 1
- Key file not found (edit, new path only): print error and exit with code 1
