"""Configuration management for asc CLI"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

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

    def __init__(self, app_name: str | None = None):
        self.app_name = app_name
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

        # Load local config to find default_app
        local_config = self._local_dir / "config.toml"
        if local_config.exists() and not self.app_name:
            try:
                local_data = self._load_toml(local_config)
                if "default_app" in local_data:
                    self.app_name = local_data["default_app"]
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

    def get(self, key: str, default: Any = None, section: str | None = None) -> Any:
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
    def issuer_id(self) -> str | None:
        return self.get("issuer_id", section="credentials") or os.getenv("ISSUER_ID")

    @property
    def key_id(self) -> str | None:
        return self.get("key_id", section="credentials") or os.getenv("KEY_ID")

    @property
    def key_file(self) -> str | None:
        key_file = self.get("key_file", section="credentials") or os.getenv("KEY_FILE")
        if key_file and key_file.startswith("~"):
            return str(Path(key_file).expanduser())
        return key_file

    @property
    def app_id(self) -> str | None:
        return self.get("app_id", section="credentials") or os.getenv("APP_ID")

    @property
    def csv_path(self) -> str:
        return self.get("csv", default="data/appstore_info.csv", section="defaults")

    @property
    def screenshots_path(self) -> str:
        return self.get("screenshots", default="data/screenshots", section="defaults")

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
csv = "data/appstore_info.csv"
screenshots = "data/screenshots"
"""
        profile_path.write_text(content)

    def remove_app_profile(self, app_name: str):
        """Remove an app profile from global config"""
        profile_path = self._global_dir / "profiles" / f"{app_name}.toml"
        if profile_path.exists():
            profile_path.unlink()
