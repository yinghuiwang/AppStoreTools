# tests/test_project_dependencies.py
from __future__ import annotations

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    import tomli as tomllib


def test_web_ui_template_dependency_is_packaged():
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text())

    dependencies = pyproject["project"]["dependencies"]

    assert any(dep.lower().startswith("jinja2") for dep in dependencies)


def test_package_version_matches_cli_version():
    from asc import __version__

    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text())

    assert __version__ == pyproject["project"]["version"]
