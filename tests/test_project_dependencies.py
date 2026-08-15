# tests/test_project_dependencies.py
from __future__ import annotations

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    import tomli as tomllib


def test_web_spa_assets_are_packaged():
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text())

    dependencies = pyproject["project"]["dependencies"]
    force_include = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]

    assert not any(dep.lower().startswith("jinja2") for dep in dependencies)
    assert force_include["src/asc/web/static/spa"] == "asc/web/static/spa"
    assert force_include["src/asc/web/locales/zh.json"] == "asc/web/locales/zh.json"
    assert force_include["src/asc/web/locales/en.json"] == "asc/web/locales/en.json"


def test_cryptography_is_not_a_hard_install_dependency():
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text())

    dependencies = pyproject["project"]["dependencies"]

    assert not any(dep.lower().startswith("cryptography") for dep in dependencies)


def test_package_version_matches_cli_version():
    from asc import __version__

    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text())

    assert __version__ == pyproject["project"]["version"]
