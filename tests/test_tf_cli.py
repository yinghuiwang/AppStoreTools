from __future__ import annotations

from types import SimpleNamespace

from typer.testing import CliRunner

from asc.cli import app
from tests.test_testflight import _build, _document

runner = CliRunner()


def test_tf_status_prints_build_and_states(monkeypatch):
    class FakeAPI:
        def list_builds(self, app_id, **params):
            assert app_id == "123"
            assert "betaAppReviewSubmission" in params["include"]
            return _document(_build("b1", "321"))

        def list_beta_groups(self, app_id):
            raise AssertionError("included groups")

    monkeypatch.setattr(
        "asc.commands.tf.resolve_app_profile",
        lambda app_name, config: "myapp",
    )
    monkeypatch.setattr(
        "asc.commands.tf.Config",
        lambda app_name=None: SimpleNamespace(app_name="myapp"),
    )
    monkeypatch.setattr(
        "asc.commands.tf.make_api_from_config",
        lambda config: (FakeAPI(), "123"),
    )
    result = runner.invoke(app, ["tf", "status", "--app", "myapp"])
    assert result.exit_code == 0, result.output
    assert "321" in result.output
    assert "External Testers" in result.output
    assert "WAITING_FOR_REVIEW" in result.output
    assert "WAITING_FOR_BETA_REVIEW" in result.output


def test_tf_status_exits_when_api_fails(monkeypatch):
    class FakeAPI:
        def list_builds(self, app_id, **params):
            raise RuntimeError("token expired")

    monkeypatch.setattr(
        "asc.commands.tf.resolve_app_profile",
        lambda app_name, config: "myapp",
    )
    monkeypatch.setattr(
        "asc.commands.tf.Config",
        lambda app_name=None: SimpleNamespace(app_name="myapp"),
    )
    monkeypatch.setattr(
        "asc.commands.tf.make_api_from_config",
        lambda config: (FakeAPI(), "123"),
    )
    monkeypatch.setattr("asc.commands.tf.get_action_hint", lambda exc: None)
    result = runner.invoke(app, ["tf", "status", "--app", "myapp"])
    assert result.exit_code == 1
    assert "token expired" in result.output or "token expired" in (result.stderr or "")
