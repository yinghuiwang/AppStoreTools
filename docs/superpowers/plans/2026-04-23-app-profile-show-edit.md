# App Profile Show & Edit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `asc app show <name>` (display all profile fields) and `asc app edit <name>` (re-prompt all fields with current values as defaults) subcommands.

**Architecture:** Add `get_app_profile(name)` to `Config` to read raw profile fields; add `cmd_app_show` and `cmd_app_edit` to `app_config.py`; register both under `app_cmd` in `cli.py`.

**Tech Stack:** Python 3.10+, typer, tomllib/tomli (already in use)

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `src/asc/config.py` | Modify | Add `get_app_profile(name) -> dict \| None` |
| `src/asc/commands/app_config.py` | Modify | Add `cmd_app_show`, `cmd_app_edit` |
| `src/asc/cli.py` | Modify | Register `show` and `edit` under `app_cmd` |
| `tests/test_app_config.py` | Create | Unit tests for show and edit commands |

---

### Task 1: Add `get_app_profile` to `Config`

**Files:**
- Modify: `src/asc/config.py` (after line 173, inside the `Config` class)
- Test: `tests/test_app_config.py` (create)

- [ ] **Step 1: Write failing test**

Create `tests/test_app_config.py`:

```python
"""Tests for cmd_app_show and cmd_app_edit."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from typer.testing import CliRunner

from asc.cli import app
from asc.config import Config

runner = CliRunner()


def _write_profile(profiles_dir: Path, name: str) -> None:
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / f"{name}.toml").write_text(
        '[credentials]\n'
        'issuer_id = "ISS-1"\n'
        'key_id = "KID-1"\n'
        'key_file = "/keys/AuthKey.p8"\n'
        'app_id = "12345"\n'
        '\n'
        '[defaults]\n'
        'csv = "data/appstore_info.csv"\n'
        'screenshots = "data/screenshots"\n'
    )


def test_get_app_profile_returns_dict(tmp_path):
    profiles_dir = tmp_path / "profiles"
    _write_profile(profiles_dir, "myapp")

    config = Config.__new__(Config)
    config._global_dir = tmp_path
    config._data = {}

    result = config.get_app_profile("myapp")

    assert result == {
        "issuer_id": "ISS-1",
        "key_id": "KID-1",
        "key_file": "/keys/AuthKey.p8",
        "app_id": "12345",
        "csv": "data/appstore_info.csv",
        "screenshots": "data/screenshots",
    }


def test_get_app_profile_missing_returns_none(tmp_path):
    config = Config.__new__(Config)
    config._global_dir = tmp_path
    config._data = {}

    result = config.get_app_profile("nonexistent")
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/wangyinghui/Documents/02-JMHS/project/tool/AppStoreTools
pytest tests/test_app_config.py::test_get_app_profile_returns_dict tests/test_app_config.py::test_get_app_profile_missing_returns_none -v
```

Expected: FAIL with `AttributeError: 'Config' object has no attribute 'get_app_profile'`

- [ ] **Step 3: Implement `get_app_profile` in `src/asc/config.py`**

Add after the `remove_app_profile` method (after line 173):

```python
    def get_app_profile(self, app_name: str) -> dict | None:
        """Return raw profile fields for app_name, or None if not found."""
        profile_path = self._global_dir / "profiles" / f"{app_name}.toml"
        if not profile_path.exists():
            return None
        data = self._load_toml(profile_path)
        creds = data.get("credentials", {})
        defaults = data.get("defaults", {})
        return {
            "issuer_id": creds.get("issuer_id", ""),
            "key_id": creds.get("key_id", ""),
            "key_file": creds.get("key_file", ""),
            "app_id": creds.get("app_id", ""),
            "csv": defaults.get("csv", "data/appstore_info.csv"),
            "screenshots": defaults.get("screenshots", "data/screenshots"),
        }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_app_config.py::test_get_app_profile_returns_dict tests/test_app_config.py::test_get_app_profile_missing_returns_none -v
```

Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/asc/config.py tests/test_app_config.py
git commit -m "feat: add Config.get_app_profile method"
```

---

### Task 2: Implement `cmd_app_show`

**Files:**
- Modify: `src/asc/commands/app_config.py`
- Test: `tests/test_app_config.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_app_config.py`:

```python
def test_cmd_app_show_prints_all_fields(tmp_path):
    profile_data = {
        "issuer_id": "ISS-1",
        "key_id": "KID-1",
        "key_file": "/keys/AuthKey.p8",
        "app_id": "12345",
        "csv": "data/appstore_info.csv",
        "screenshots": "data/screenshots",
    }
    with patch("asc.commands.app_config.Config") as MockConfig:
        mock_cfg = MagicMock()
        mock_cfg.get_app_profile.return_value = profile_data
        MockConfig.return_value = mock_cfg

        result = runner.invoke(app, ["app", "show", "myapp"])

    assert result.exit_code == 0
    assert "myapp" in result.output
    assert "ISS-1" in result.output
    assert "KID-1" in result.output
    assert "/keys/AuthKey.p8" in result.output
    assert "12345" in result.output
    assert "data/appstore_info.csv" in result.output
    assert "data/screenshots" in result.output


def test_cmd_app_show_missing_profile_exits_1():
    with patch("asc.commands.app_config.Config") as MockConfig:
        mock_cfg = MagicMock()
        mock_cfg.get_app_profile.return_value = None
        MockConfig.return_value = mock_cfg

        result = runner.invoke(app, ["app", "show", "ghost"])

    assert result.exit_code == 1
    assert "not found" in result.output.lower() or "找不到" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_app_config.py::test_cmd_app_show_prints_all_fields tests/test_app_config.py::test_cmd_app_show_missing_profile_exits_1 -v
```

Expected: FAIL with `No such command 'show'`

- [ ] **Step 3: Implement `cmd_app_show` in `src/asc/commands/app_config.py`**

Add after `cmd_app_default` (after line 169):

```python
def cmd_app_show(
    name: str = typer.Argument(..., help="Profile name to display"),
):
    """Show all fields of an app profile.

    \\b
    Example:
        asc app show myapp
    """
    config = Config()
    profile = config.get_app_profile(name)
    if profile is None:
        typer.echo(f"❌ Profile '{name}' not found.", err=True)
        raise typer.Exit(1)

    typer.echo(f"App profile: {name}")
    typer.echo(f"  Issuer ID:        {profile['issuer_id']}")
    typer.echo(f"  Key ID:           {profile['key_id']}")
    typer.echo(f"  Key file:         {profile['key_file']}")
    typer.echo(f"  App ID:           {profile['app_id']}")
    typer.echo(f"  CSV path:         {profile['csv']}")
    typer.echo(f"  Screenshots path: {profile['screenshots']}")
```

- [ ] **Step 4: Register `show` in `src/asc/cli.py`**

In `cli.py`, update the import line (line 78):

```python
from asc.commands.app_config import cmd_app_add, cmd_app_list, cmd_app_remove, cmd_app_default, cmd_install, cmd_app_show
```

Add after `app_cmd.command("default")(cmd_app_default)` (line 97):

```python
app_cmd.command("show")(cmd_app_show)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_app_config.py::test_cmd_app_show_prints_all_fields tests/test_app_config.py::test_cmd_app_show_missing_profile_exits_1 -v
```

Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add src/asc/commands/app_config.py src/asc/cli.py tests/test_app_config.py
git commit -m "feat: add asc app show command"
```

---

### Task 3: Implement `cmd_app_edit`

**Files:**
- Modify: `src/asc/commands/app_config.py`
- Test: `tests/test_app_config.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_app_config.py`:

```python
def test_cmd_app_edit_missing_profile_exits_1():
    with patch("asc.commands.app_config.Config") as MockConfig:
        mock_cfg = MagicMock()
        mock_cfg.get_app_profile.return_value = None
        MockConfig.return_value = mock_cfg

        result = runner.invoke(app, ["app", "edit", "ghost"])

    assert result.exit_code == 1


def test_cmd_app_edit_keeps_existing_values_on_enter(tmp_path):
    """Pressing Enter for all fields keeps original values and calls save_app_profile."""
    profile_data = {
        "issuer_id": "ISS-1",
        "key_id": "KID-1",
        "key_file": "/keys/AuthKey.p8",
        "app_id": "12345",
        "csv": "data/appstore_info.csv",
        "screenshots": "data/screenshots",
    }
    # Simulate user pressing Enter for every field (keep defaults)
    user_input = "\n\n\n\n\n\n"

    with patch("asc.commands.app_config.Config") as MockConfig, \
         patch("asc.commands.app_config.shutil") as mock_shutil:
        mock_cfg = MagicMock()
        mock_cfg.get_app_profile.return_value = profile_data
        MockConfig.return_value = mock_cfg

        result = runner.invoke(app, ["app", "edit", "myapp"], input=user_input)

    assert result.exit_code == 0
    mock_cfg.save_app_profile.assert_called_once_with(
        "myapp", "ISS-1", "KID-1", "/keys/AuthKey.p8", "12345",
        "data/appstore_info.csv", "data/screenshots",
    )
    # No file copy when key_file unchanged
    mock_shutil.copy2.assert_not_called()


def test_cmd_app_edit_new_key_file_is_copied(tmp_path):
    """When user provides a new key file path, it is copied to the keys dir."""
    profile_data = {
        "issuer_id": "ISS-1",
        "key_id": "KID-1",
        "key_file": "/keys/AuthKey.p8",
        "app_id": "12345",
        "csv": "data/appstore_info.csv",
        "screenshots": "data/screenshots",
    }
    new_key = tmp_path / "NewKey.p8"
    new_key.write_text("fake key content")

    # Enter new key path, keep everything else
    user_input = f"\n\n{new_key}\n\n\n\n"

    with patch("asc.commands.app_config.Config") as MockConfig:
        mock_cfg = MagicMock()
        mock_cfg.get_app_profile.return_value = profile_data
        mock_cfg._global_dir = tmp_path
        MockConfig.return_value = mock_cfg

        result = runner.invoke(app, ["app", "edit", "myapp"], input=user_input)

    assert result.exit_code == 0
    expected_dest = tmp_path / "keys" / new_key.name
    mock_cfg.save_app_profile.assert_called_once()
    call_args = mock_cfg.save_app_profile.call_args[0]
    assert call_args[3] == str(expected_dest)


def test_cmd_app_edit_new_key_file_not_found_exits_1(tmp_path):
    """When user provides a non-existent key file path, exit with code 1."""
    profile_data = {
        "issuer_id": "ISS-1",
        "key_id": "KID-1",
        "key_file": "/keys/AuthKey.p8",
        "app_id": "12345",
        "csv": "data/appstore_info.csv",
        "screenshots": "data/screenshots",
    }
    user_input = "\n\n/nonexistent/key.p8\n\n\n\n"

    with patch("asc.commands.app_config.Config") as MockConfig:
        mock_cfg = MagicMock()
        mock_cfg.get_app_profile.return_value = profile_data
        MockConfig.return_value = mock_cfg

        result = runner.invoke(app, ["app", "edit", "myapp"], input=user_input)

    assert result.exit_code == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_app_config.py::test_cmd_app_edit_missing_profile_exits_1 tests/test_app_config.py::test_cmd_app_edit_keeps_existing_values_on_enter tests/test_app_config.py::test_cmd_app_edit_new_key_file_is_copied tests/test_app_config.py::test_cmd_app_edit_new_key_file_not_found_exits_1 -v
```

Expected: FAIL with `No such command 'edit'`

- [ ] **Step 3: Implement `cmd_app_edit` in `src/asc/commands/app_config.py`**

Add after `cmd_app_show`:

```python
def cmd_app_edit(
    name: str = typer.Argument(..., help="Profile name to edit"),
):
    """Interactively re-edit an existing app profile.

    Re-prompts all fields with current values as defaults.
    Press Enter to keep the existing value for any field.

    \\b
    Example:
        asc app edit myapp
    """
    config = Config()
    profile = config.get_app_profile(name)
    if profile is None:
        typer.echo(f"❌ Profile '{name}' not found.", err=True)
        raise typer.Exit(1)

    typer.echo(f"Editing app profile: {name}")
    typer.echo("Press Enter to keep the current value.\n")

    issuer_id = typer.prompt("  Issuer ID", default=profile["issuer_id"])
    key_id = typer.prompt("  Key ID", default=profile["key_id"])
    key_file_input = typer.prompt("  Path to .p8 private key file", default=profile["key_file"])
    app_id = typer.prompt("  App ID (numeric)", default=profile["app_id"])
    csv_path = typer.prompt("  CSV metadata file path", default=profile["csv"])
    screenshots_path = typer.prompt("  Screenshots directory", default=profile["screenshots"])

    # Only copy key file if user provided a new path
    if key_file_input != profile["key_file"]:
        new_key_path = Path(key_file_input).expanduser()
        if not new_key_path.exists():
            typer.echo(f"❌ Key file not found: {new_key_path}", err=True)
            raise typer.Exit(1)
        global_keys_dir = config._global_dir / "keys"
        global_keys_dir.mkdir(parents=True, exist_ok=True)
        dest_key = global_keys_dir / new_key_path.name
        shutil.copy2(new_key_path, dest_key)
        typer.echo(f"  ✅ Key file copied to {dest_key}")
        final_key_file = str(dest_key)
    else:
        final_key_file = profile["key_file"]

    config.save_app_profile(name, issuer_id, key_id, final_key_file, app_id, csv_path, screenshots_path)
    typer.echo(f"\n✅ App profile '{name}' updated.")
```

- [ ] **Step 4: Register `edit` in `src/asc/cli.py`**

Update the import line:

```python
from asc.commands.app_config import cmd_app_add, cmd_app_list, cmd_app_remove, cmd_app_default, cmd_install, cmd_app_show, cmd_app_edit
```

Add after `app_cmd.command("show")(cmd_app_show)`:

```python
app_cmd.command("edit")(cmd_app_edit)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_app_config.py -v
```

Expected: all tests pass

- [ ] **Step 6: Run full test suite to check for regressions**

```bash
pytest --tb=short -q
```

Expected: all tests pass (no regressions)

- [ ] **Step 7: Commit**

```bash
git add src/asc/commands/app_config.py src/asc/cli.py tests/test_app_config.py
git commit -m "feat: add asc app edit command"
```
