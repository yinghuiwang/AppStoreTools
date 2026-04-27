# tests/test_init_cmd.py
"""Tests for asc init command"""
from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from asc.cli import app

runner = CliRunner()


@pytest.fixture()
def xcode_project(tmp_path):
    """A tmp dir with a .xcodeproj so it looks like an Xcode project."""
    (tmp_path / "MyApp.xcodeproj").mkdir()
    return tmp_path


@pytest.fixture()
def non_xcode_dir(tmp_path):
    """A tmp dir with no Xcode markers."""
    return tmp_path


def test_init_creates_appstore_structure(xcode_project):
    """init creates AppStore/ with expected dirs and files in an Xcode project dir."""
    result = runner.invoke(app, ["init", "--path", str(xcode_project)])
    assert result.exit_code == 0, result.output

    appstore = xcode_project / "AppStore"
    assert (appstore / "Config").is_dir()
    assert (appstore / "Config" / ".env.example").is_file()
    assert (appstore / "Config" / ".gitignore").is_file()
    assert (appstore / "data").is_dir()
    assert (appstore / "data" / "appstore_info.csv").is_file()
    assert (appstore / "data" / "screenshots").is_dir()
    assert (appstore / "data" / "iap_packages.json").is_file()
    assert (appstore / "data" / "iap_review").is_dir()
    assert any((appstore / "data" / "iap_review").iterdir())  # has at least one file


def test_init_env_example_contains_placeholders(xcode_project):
    """Generated .env.example has all four required keys."""
    runner.invoke(app, ["init", "--path", str(xcode_project)])
    content = (xcode_project / "AppStore" / "Config" / ".env.example").read_text()
    for key in ("ISSUER_ID", "KEY_ID", "KEY_FILE", "APP_ID"):
        assert key in content


def test_init_gitignore_ignores_env_not_example(xcode_project):
    """.gitignore blocks .env but not .env.example."""
    runner.invoke(app, ["init", "--path", str(xcode_project)])
    content = (xcode_project / "AppStore" / "Config" / ".gitignore").read_text()
    assert ".env" in content
    assert ".env.example" not in content.replace("# .env.example", "")


def test_init_csv_has_header_row(xcode_project):
    """Generated appstore_info.csv has the required header columns."""
    runner.invoke(app, ["init", "--path", str(xcode_project)])
    content = (xcode_project / "AppStore" / "data" / "appstore_info.csv").read_text()
    assert "语言" in content
    assert "应用名称" in content
    assert "关键子" in content


def test_init_iap_json_is_valid_json(xcode_project):
    """Generated iap_packages.json is valid JSON with subscriptionGroups key."""
    import json
    runner.invoke(app, ["init", "--path", str(xcode_project)])
    content = (xcode_project / "AppStore" / "data" / "iap_packages.json").read_text()
    data = json.loads(content)
    assert "subscriptionGroups" in data or "items" in data


def test_init_non_xcode_dir_exits_nonzero(non_xcode_dir):
    """init exits with code 1 and an error message if no Xcode project detected."""
    result = runner.invoke(app, ["init", "--path", str(non_xcode_dir)])
    assert result.exit_code == 1
    assert "Xcode" in result.output or "xcodeproj" in result.output.lower()


def test_init_already_has_appstore_skips(xcode_project):
    """init exits 0 with a message when AppStore/ already exists — no overwrite."""
    (xcode_project / "AppStore").mkdir()
    result = runner.invoke(app, ["init", "--path", str(xcode_project)])
    assert result.exit_code == 0
    assert "already" in result.output.lower() or "已存在" in result.output


def test_init_idempotent_partial_appstore(xcode_project):
    """init creates missing subdirs even if AppStore/ partially exists."""
    appstore = xcode_project / "AppStore"
    appstore.mkdir()
    (appstore / "Config").mkdir()
    # data/ is missing — init should create it without error
    result = runner.invoke(app, ["init", "--path", str(xcode_project)])
    assert result.exit_code == 0
    assert (appstore / "data").is_dir()


def test_init_xcworkspace_also_detected(tmp_path):
    """init also recognises .xcworkspace as an Xcode project marker."""
    (tmp_path / "MyApp.xcworkspace").mkdir()
    result = runner.invoke(app, ["init", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "AppStore").is_dir()


def test_init_default_path_is_cwd(xcode_project, monkeypatch):
    """When --path is omitted, init uses current working directory."""
    monkeypatch.chdir(xcode_project)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert (xcode_project / "AppStore").is_dir()
