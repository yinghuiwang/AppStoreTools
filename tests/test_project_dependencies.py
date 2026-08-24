# tests/test_project_dependencies.py
from __future__ import annotations

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    import tomli as tomllib


def test_web_spa_assets_are_packaged():
    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text())

    dependencies = pyproject["project"]["dependencies"]
    wheel = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]
    force_include = wheel.get("force-include", {})
    spa_index = root / "src" / "asc" / "web" / "static" / "spa" / "index.html"

    assert not any(dep.lower().startswith("jinja2") for dep in dependencies)
    assert wheel["packages"] == ["src/asc"]
    # hatchling>=1.30 errors if force-include restates files already in packages.
    overlapping = [
        source
        for source in force_include
        if source == "src/asc" or source.startswith("src/asc/")
    ]
    assert overlapping == []
    assert spa_index.is_file()
    assert "/static/spa/assets/" in spa_index.read_text(encoding="utf-8")
    assert list((spa_index.parent / "assets").glob("index-*.js"))


def test_cryptography_is_not_a_hard_install_dependency():
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text())

    dependencies = pyproject["project"]["dependencies"]

    assert any(dep.replace(" ", "").startswith("PyJWT[crypto]") for dep in dependencies)
    assert not any(dep.lower().startswith("cryptography") for dep in dependencies)


def test_package_version_matches_cli_version():
    from asc import __version__

    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text())

    assert __version__ == pyproject["project"]["version"]
