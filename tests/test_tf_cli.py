from __future__ import annotations

from types import SimpleNamespace

from typer.testing import CliRunner

from asc.cli import app
from asc.i18n import TF_TEXT, t
from tests.test_testflight import GroupFirstAPI

runner = CliRunner()


def _install_api(monkeypatch, api):
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
        lambda config: (api, "123"),
    )


def test_tf_status_prints_build_and_states(monkeypatch):
    api = GroupFirstAPI()
    _install_api(monkeypatch, api)
    result = runner.invoke(app, ["tf", "status", "--app", "myapp"])
    assert result.exit_code == 0, result.output
    assert "321" in result.output
    assert "Public" in result.output
    assert "WAITING_FOR_REVIEW" in result.output
    assert "WAITING_FOR_BETA_REVIEW" in result.output
    assert any(call[0] == "list_beta_group_builds" for call in api.calls)


def test_tf_status_explains_no_external_groups(monkeypatch):
    api = GroupFirstAPI(
        groups=[{"id": "g-int", "attributes": {"name": "QA", "isInternalGroup": True}}],
        group_builds={},
    )
    _install_api(monkeypatch, api)
    result = runner.invoke(app, ["tf", "status", "--app", "myapp"])
    assert result.exit_code == 0, result.output
    assert t(TF_TEXT["no_external_groups"]) in result.output
    assert not any(call[0] == "list_beta_group_builds" for call in api.calls)


def test_tf_status_prints_only_current_reviewed_build(monkeypatch):
    from tests.test_testflight import _group_build

    api = GroupFirstAPI(
        group_builds={
            "g-ext": {
                "data": [
                    _group_build("b9", "9"),
                    _group_build("b100", "100"),
                    _group_build("b10", "10"),
                ],
                "included": [],
            }
        },
        hydrate={"data": [], "included": []},
        submissions={
            "b100": [],
            "b10": [{"id": "s10", "attributes": {"betaReviewState": "IN_REVIEW"}}],
            "b9": [{"id": "s9", "attributes": {"betaReviewState": "APPROVED"}}],
        },
        details={
            "b100": {"id": "d100", "attributes": {"externalBuildState": "PROCESSING"}},
            "b10": {"id": "d10", "attributes": {"externalBuildState": "IN_BETA_REVIEW"}},
            "b9": {"id": "d9", "attributes": {"externalBuildState": "BETA_APPROVED"}},
        },
    )
    _install_api(monkeypatch, api)
    result = runner.invoke(app, ["tf", "status", "--app", "myapp"])
    assert result.exit_code == 0, result.output
    assert "10" in result.output
    assert "IN_REVIEW" in result.output
    assert "IN_BETA_REVIEW" in result.output
    assert "100" not in result.output
    assert "APPROVED" not in result.output
    assert " 9 " not in f" {result.output} "


def test_tf_status_prints_not_submitted(monkeypatch):
    api = GroupFirstAPI(
        submissions={"b1": []},
        details={"b1": {"id": "d1", "attributes": {"externalBuildState": "READY_FOR_BETA_SUBMISSION"}}},
    )
    _install_api(monkeypatch, api)
    result = runner.invoke(app, ["tf", "status", "--app", "myapp"])
    assert result.exit_code == 0, result.output
    assert t(TF_TEXT["not_submitted"]) in result.output
    assert "READY_FOR_BETA_SUBMISSION" in result.output


def test_tf_status_exits_when_api_fails(monkeypatch):
    class FakeAPI:
        def list_beta_groups(self, app_id, **params):
            raise RuntimeError("token expired")

    _install_api(monkeypatch, FakeAPI())
    monkeypatch.setattr("asc.commands.tf.get_action_hint", lambda exc: None)
    result = runner.invoke(app, ["tf", "status", "--app", "myapp"])
    assert result.exit_code == 1
    assert "token expired" in result.output or "token expired" in (result.stderr or "")
