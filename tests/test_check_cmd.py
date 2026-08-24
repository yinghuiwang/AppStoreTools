from __future__ import annotations

from types import SimpleNamespace

from typer.testing import CliRunner

from asc.cli import app

runner = CliRunner()


def test_check_prints_connected_app(monkeypatch):
    class FakeAPI:
        def get_app(self, app_id):
            assert app_id == "123"
            return {"data": {"attributes": {"name": "Demo App", "bundleId": "com.demo.app"}}}

    monkeypatch.setattr(
        "asc.commands.metadata.resolve_app_profile",
        lambda app_name, config: "myapp",
    )
    monkeypatch.setattr(
        "asc.commands.metadata.Config",
        lambda app_name=None: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "asc.commands.metadata.make_api_from_config",
        lambda config: (FakeAPI(), "123"),
    )
    result = runner.invoke(app, ["check", "--app", "myapp"])
    assert result.exit_code == 0
    assert "Demo App" in result.output
    assert "com.demo.app" in result.output


def test_check_exits_when_api_fails(monkeypatch):
    class FakeAPI:
        def get_app(self, app_id):
            raise RuntimeError("token expired")

    monkeypatch.setattr(
        "asc.commands.metadata.resolve_app_profile",
        lambda app_name, config: "myapp",
    )
    monkeypatch.setattr(
        "asc.commands.metadata.Config",
        lambda app_name=None: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "asc.commands.metadata.make_api_from_config",
        lambda config: (FakeAPI(), "123"),
    )
    monkeypatch.setattr("asc.commands.metadata.get_action_hint", lambda exc: None)
    result = runner.invoke(app, ["check", "--app", "myapp"])
    assert result.exit_code == 1
    assert "token expired" in result.output or "token expired" in (result.stderr or "")
