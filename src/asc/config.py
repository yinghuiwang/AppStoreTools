"""Configuration management for asc CLI"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

from dotenv import load_dotenv


class Config:
    """Configuration with priority: CLI args > local .asc/config.toml > global profile > env"""

    def __init__(self, app_name: Optional[str] = None):
        # CLI args take priority, then env var, then local config
        self.app_name = app_name or os.getenv("_ASC_APP")
        self._global_dir = Path.home() / ".config" / "asc"
        self._local_dir = Path.cwd() / ".asc"
        self._data: dict[str, Any] = {}
        self._load()

    def _load_toml(self, path: Path) -> dict:
        if tomllib is None:
            raise ImportError(
                "tomllib/tomli not available. Install: pip install tomli"
            )
        with open(path, "rb") as f:
            return tomllib.load(f)

    def _load(self):
        # Load from environment variables (lowest priority)
        env_file = Path.cwd() / "config" / ".env"
        if env_file.exists():
            load_dotenv(env_file)

        # Load local config
        local_config = self._local_dir / "config.toml"
        local_data = {}
        if local_config.exists():
            try:
                local_data = self._load_toml(local_config)
                # Support both top-level default_app and [defaults] section
                if not self.app_name:
                    if "default_app" in local_data:
                        self.app_name = local_data["default_app"]
                    elif "defaults" in local_data and "default_app" in local_data["defaults"]:
                        self.app_name = local_data["defaults"]["default_app"]
            except Exception:
                pass

        # Load global profile
        if self.app_name:
            global_profile = self._global_dir / "profiles" / f"{self.app_name}.toml"
            if global_profile.exists():
                try:
                    self._data = self._load_toml(global_profile)
                except Exception:
                    pass

        # Merge local data (higher priority than global)
        for k, v in local_data.items():
            if isinstance(v, dict) and k in self._data and isinstance(self._data[k], dict):
                self._data[k].update(v)
            else:
                self._data[k] = v

    def get(self, key: str, default: Any = None, section: Optional[str] = None) -> Any:
        """Get config value with fallback to environment variable"""
        if section and section in self._data:
            value = self._data[section].get(key)
            if value is not None:
                return value
        elif not section and key in self._data:
            return self._data[key]

        # Fallback to environment variable (uppercase)
        env_value = os.getenv(key.upper())
        if env_value:
            return env_value

        return default

    @property
    def issuer_id(self) -> Optional[str]:
        return self.get("issuer_id", section="credentials") or os.getenv("ISSUER_ID")

    @property
    def key_id(self) -> Optional[str]:
        return self.get("key_id", section="credentials") or os.getenv("KEY_ID")

    @property
    def key_file(self) -> Optional[str]:
        key_file = self.get("key_file", section="credentials") or os.getenv("KEY_FILE")
        if key_file and key_file.startswith("~"):
            return str(Path(key_file).expanduser())
        return key_file

    @property
    def app_id(self) -> Optional[str]:
        return self.get("app_id", section="credentials") or os.getenv("APP_ID")

    @property
    def csv_path(self) -> str:
        return self.get("csv", default="data/appstore_info.csv", section="defaults")

    @property
    def screenshots_path(self) -> str:
        return self.get("screenshots", default="data/screenshots", section="defaults")

    @property
    def build_project(self) -> Optional[str]:
        return self.get("project", section="build")

    @property
    def build_scheme(self) -> Optional[str]:
        return self.get("scheme", section="build")

    @property
    def build_output(self) -> str:
        return self.get("output", default="build", section="build")

    @property
    def build_signing(self) -> str:
        return self.get("signing", default="auto", section="build")

    @property
    def build_bundle_id(self) -> Optional[str]:
        return self.get("bundle_id", section="build")

    @property
    def build_certificate(self) -> Optional[str]:
        return self.get("certificate", section="build")

    @property
    def build_profile(self) -> Optional[str]:
        return self.get("profile", section="build")

    @property
    def build_destination(self) -> Optional[str]:
        return self.get("destination", section="build")

    def list_apps(self) -> list[str]:
        """List all configured app profiles"""
        profiles_dir = self._global_dir / "profiles"
        if not profiles_dir.exists():
            return []
        return [p.stem for p in sorted(profiles_dir.glob("*.toml"))]

    def save_app_profile(
        self,
        app_name: str,
        issuer_id: str,
        key_id: str,
        key_file: str,
        app_id: str,
        csv: str = "data/appstore_info.csv",
        screenshots: str = "data/screenshots",
    ):
        """Save a new app profile to global config"""
        profiles_dir = self._global_dir / "profiles"
        profiles_dir.mkdir(parents=True, exist_ok=True)

        profile_path = profiles_dir / f"{app_name}.toml"
        content = f"""[credentials]
issuer_id = "{issuer_id}"
key_id = "{key_id}"
key_file = "{key_file}"
app_id = "{app_id}"

[defaults]
csv = "{csv}"
screenshots = "{screenshots}"
"""
        profile_path.write_text(content)

    def update_local_build_section(self, updates: dict) -> None:
        """Merge `updates` into [build] of ./.asc/config.toml; create if missing.

        Preserves all other sections and keys verbatim. Only string values supported.
        None values are skipped.
        """
        if tomllib is None:
            raise ImportError("tomllib/tomli not available")

        self._local_dir.mkdir(parents=True, exist_ok=True)
        cfg_path = self._local_dir / "config.toml"

        data: dict = {}
        if cfg_path.exists():
            try:
                data = self._load_toml(cfg_path)
            except Exception:
                data = {}

        build = dict(data.get("build", {}))
        for k, v in updates.items():
            if v is None:
                continue
            build[k] = str(v)
        data["build"] = build

        lines: list[str] = []
        for section, items in data.items():
            if not isinstance(items, dict):
                continue
            lines.append(f"[{section}]")
            for k, v in items.items():
                escaped = str(v).replace("\\", "\\\\").replace('"', '\\"')
                lines.append(f'{k} = "{escaped}"')
            lines.append("")
        cfg_path.write_text("\n".join(lines).rstrip() + "\n")

    def remove_app_profile(self, app_name: str):
        """Remove an app profile from global config"""
        profile_path = self._global_dir / "profiles" / f"{app_name}.toml"
        if profile_path.exists():
            profile_path.unlink()

    def get_app_profile(self, app_name: str) -> Optional[dict]:
        """Return raw profile fields for app_name, or None if not found or unreadable."""
        profile_path = self._global_dir / "profiles" / f"{app_name}.toml"
        if not profile_path.exists():
            return None
        try:
            data = self._load_toml(profile_path)
        except Exception:
            return None
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
