# Install Command Design

**Date:** 2026-04-23  
**Status:** Approved

## Overview

Two-part installation system:

1. **`install.sh`** — shell script for environment checks and `asc` tool installation (runs before `asc` exists)
2. **`asc install`** — CLI subcommand for project-level initialization and optional App profile setup

## Part 1: `install.sh`

**Location:** `install.sh` (project root)

**Usage:**
```bash
bash install.sh
# or via curl
curl -fsSL https://raw.githubusercontent.com/.../install.sh | bash
```

**Execution flow:**

1. Detect OS (macOS / Linux)
2. Check Python 3.9+
   - Missing or too old → print platform-specific install instructions and exit
   - macOS: `brew install python@3.12`
   - Linux: `apt install python3` / `pyenv` suggestion
3. Check pip
   - Missing → attempt `python3 -m ensurepip --upgrade`
   - If that fails → print manual install instructions and exit
4. Check git (non-blocking warning if missing)
5. Check brew on macOS (non-blocking suggestion if missing)
6. Run `pip install asc-appstore-tools`
7. Verify `asc --version` succeeds
8. Print success message and prompt: `Run 'asc install' to set up your project`

**Exit codes:**
- `0` — success
- `1` — fatal error (Python missing/incompatible, pip install failed)

## Part 2: `asc install`

**Implementation:** `cmd_install` in `src/asc/commands/app_config.py`, registered as `asc install` in `cli.py`

**Reuses:** `cmd_app_add`, `cmd_app_default` — no logic duplication

**Execution flow:**

1. Print welcome banner
2. Check current directory state:
   - `.asc/config.toml` exists with `default_app` → print "Environment ready", show current config, exit
   - Otherwise → continue
3. List existing profiles via `config.list_apps()`
   - Profiles exist → show list, offer to set one as default
   - No profiles → skip to step 4
4. Ask: "Configure an App profile now? [y/N]"
   - Yes → run `asc app add` interactive flow, then offer `asc app default`
   - No → print next steps and exit
5. Print quick-reference command cheatsheet on completion

**Command relationship:**

| Command | Role |
|---------|------|
| `asc app add <name>` | Add a single profile (existing) |
| `asc app default <name>` | Set default profile (existing) |
| `asc install` | Guided initialization: add + set default (new) |

## Files Changed

| File | Change |
|------|--------|
| `install.sh` | New file |
| `src/asc/commands/app_config.py` | Add `cmd_install` |
| `src/asc/cli.py` | Register `asc install` command |
