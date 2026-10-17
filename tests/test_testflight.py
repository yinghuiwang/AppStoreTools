from __future__ import annotations

from pathlib import Path
from unittest.mock import call, patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from asc.api import AppStoreConnectAPI
from asc.schedule import query_review, query_testflight
from asc.testflight import (
    TestFlightBuild,
    apply_beta_groups,
    classify_testflight_builds,
    fetch_testflight_builds,
    parse_testflight_builds,
)


@pytest.fixture
def api(tmp_path):
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_file = tmp_path / "AuthKey_TEST.p8"
    key_file.write_bytes(pem)
    return AppStoreConnectAPI(
        issuer_id="test-issuer",
        key_id="TESTKEYID",
        key_file=str(key_file),
    )


def _build(
    build_id="b1",
    version="123",
    *,
    expired=False,
    beta_review="WAITING_FOR_REVIEW",
    external="WAITING_FOR_BETA_REVIEW",
    groups=None,
    group_included=True,
    internal=False,
    group_id="g-ext",
):
    group_id = group_id
    relationships = {
        "betaAppReviewSubmission": {
            "data": {"type": "betaAppReviewSubmissions", "id": f"sub-{build_id}"}
        },
        "buildBetaDetail": {
            "data": {"type": "buildBetaDetails", "id": f"det-{build_id}"}
        },
        "betaGroups": {
            "data": [{"type": "betaGroups", "id": group_id}],
        },
    }
    included = [
        {
            "type": "betaAppReviewSubmissions",
            "id": f"sub-{build_id}",
            "attributes": {"betaReviewState": beta_review},
        },
        {
            "type": "buildBetaDetails",
            "id": f"det-{build_id}",
            "attributes": {"externalBuildState": external},
        },
    ]
    if group_included:
        included.append(
            {
                "type": "betaGroups",
                "id": group_id,
                "attributes": {
                    "name": (groups or ["External Testers"])[0],
                    "isInternalGroup": internal,
                },
            }
        )
    return {
        "data": {
            "type": "builds",
            "id": build_id,
            "attributes": {
                "version": version,
                "expired": expired,
                "uploadedDate": "2026-10-14T01:00:00Z",
            },
            "relationships": relationships,
        },
        "included": included,
    }


def _document(*parts):
    data = []
    included = []
    seen = set()
    for part in parts:
        data.append(part["data"])
        for item in part["included"]:
            key = (item["type"], item["id"])
            if key in seen:
                continue
            seen.add(key)
            included.append(item)
    return {"data": data, "included": included}


def test_parse_reads_include_and_skips_internal_groups():
    document = _document(
        _build("b1", "123"),
        _build("b2", "122", internal=True, external="IN_BETA_TESTING", group_id="g-int"),
    )
    builds = parse_testflight_builds(document)
    assert [item.version for item in builds] == ["123", "122"]
    assert builds[0].beta_review_state == "WAITING_FOR_REVIEW"
    assert builds[0].external_build_state == "WAITING_FOR_BETA_REVIEW"
    assert builds[0].external_groups == ["External Testers"]
    assert builds[0].has_external_group is True
    assert builds[1].external_groups == []
    assert builds[1].has_external_group is False


def test_unresolved_groups_are_filled_from_beta_groups_list():
    document = _document(_build("b1", "123", group_included=False))
    builds = parse_testflight_builds(document)
    assert builds[0].unresolved_group_ids == ["g-ext"]
    apply_beta_groups(
        builds,
        [
            {
                "id": "g-ext",
                "attributes": {"name": "Public", "isInternalGroup": False},
            }
        ],
    )
    assert builds[0].external_groups == ["Public"]
    assert builds[0].unresolved_group_ids == []


def test_classify_only_external_review_states():
    builds = [
        TestFlightBuild("a", "123", False, "", "WAITING_FOR_REVIEW", "WAITING_FOR_BETA_REVIEW", ["External"]),
        TestFlightBuild("b", "122", False, "", "APPROVED", "READY_FOR_BETA_TESTING", ["Public"]),
        TestFlightBuild("c", "121", False, "", "IN_REVIEW", "IN_BETA_REVIEW", []),
        TestFlightBuild("d", "120", True, "", "WAITING_FOR_REVIEW", "WAITING_FOR_BETA_REVIEW", ["External"]),
        TestFlightBuild("e", "119", False, "", "", "READY_FOR_BETA_SUBMISSION", ["External"]),
        TestFlightBuild("f", "118", False, "", "REJECTED", "BETA_REJECTED", ["External"]),
    ]
    in_review, ready = classify_testflight_builds(builds)
    assert in_review == [
        ("123（External）", "等待 Beta 审核"),
        ("119（External）", "未送审"),
        ("118（External）", "Beta 被拒"),
    ]
    assert ready == []


def test_classify_ready_when_no_review():
    builds = [
        TestFlightBuild("a", "122", False, "", "APPROVED", "IN_BETA_TESTING", ["Public"]),
    ]
    in_review, ready = classify_testflight_builds(builds)
    assert in_review == []
    assert ready == ["122（Public）"]


def test_classify_falls_back_to_beta_review_state():
    builds = [
        TestFlightBuild("a", "99", False, "", "IN_REVIEW", "", ["External"]),
    ]
    in_review, ready = classify_testflight_builds(builds)
    assert in_review == [("99（External）", "Beta 审核中")]
    assert ready == []


def test_fetch_uses_include_and_skips_group_list_when_complete():
    # Replaced by test_fetch_uses_external_group_builds_not_app_wide_include:
    # live ASC does not reliably include betaGroups on GET /v1/builds.
    api = GroupFirstAPI(hydrate=_document(_build("b1", "321", groups=["Public"])))
    result = fetch_testflight_builds(api, "app-1")
    assert [item.version for item in result.builds] == ["321"]
    assert result.builds[0].external_groups == ["Public"]
    assert any(call[0] == "list_beta_group_builds" for call in api.calls)


def test_fetch_lists_groups_only_when_unresolved():
    api = GroupFirstAPI(
        hydrate={"data": [{"type": "builds", "id": "b1", "attributes": {"version": "321"}}], "included": []},
    )
    result = fetch_testflight_builds(api, "app-1")
    assert result.builds[0].external_groups == ["Public"]
    assert result.builds[0].beta_review_state == "WAITING_FOR_REVIEW"


def test_list_builds_collects_included_across_pages(api):
    with patch.object(
        api,
        "get",
        side_effect=[
            {
                "data": [{"type": "builds", "id": "b1", "attributes": {"version": "1"}}],
                "included": [
                    {"type": "betaGroups", "id": "g1", "attributes": {"name": "A", "isInternalGroup": False}},
                ],
                "links": {"next": "https://api.example/v1/builds?page=2"},
            },
            {
                "data": [{"type": "builds", "id": "b2", "attributes": {"version": "2"}}],
                "included": [
                    {"type": "betaGroups", "id": "g1", "attributes": {"name": "A", "isInternalGroup": False}},
                    {"type": "buildBetaDetails", "id": "d2", "attributes": {"externalBuildState": "IN_BETA_REVIEW"}},
                ],
                "links": {},
            },
        ],
    ) as mock_get:
        document = api.list_builds(
            "app-1",
            include="betaAppReviewSubmission,buildBetaDetail,betaGroups",
        )

    assert [item["id"] for item in document["data"]] == ["b1", "b2"]
    assert [item["id"] for item in document["included"]] == ["g1", "d2"]
    assert mock_get.call_args_list[0] == call(
        "/v1/builds",
        **{
            "filter[app]": "app-1",
            "limit": 200,
            "include": "betaAppReviewSubmission,buildBetaDetail,betaGroups",
        },
    )


def test_beta_group_and_review_endpoints(api):
    with patch.object(
        api,
        "get",
        side_effect=[
            {"data": [{"id": "g1", "attributes": {"isInternalGroup": False}}], "links": {}},
            {"data": [{"id": "s1", "attributes": {"betaReviewState": "IN_REVIEW"}}], "links": {}},
            {"data": {"id": "d1", "attributes": {"externalBuildState": "BETA_APPROVED"}}},
        ],
    ) as mock_get:
        groups = api.list_beta_groups("app-1")
        submissions = api.list_beta_app_review_submissions("b1")
        detail = api.get_build_beta_detail("b1")

    assert groups[0]["id"] == "g1"
    assert submissions[0]["attributes"]["betaReviewState"] == "IN_REVIEW"
    assert detail["attributes"]["externalBuildState"] == "BETA_APPROVED"
    assert mock_get.call_args_list == [
        call("/v1/betaGroups", **{"filter[app]": "app-1", "limit": 200}),
        call("/v1/betaAppReviewSubmissions", **{"filter[build]": "b1"}),
        call("/v1/builds/b1/buildBetaDetail"),
    ]


def _creds(tmp_path: Path) -> dict:
    key = tmp_path / "AuthKey.p8"
    key.write_bytes(b"not-a-real-key")
    return {
        "issuer_id": "issuer",
        "key_id": "KEYID",
        "key_file": str(key),
        "app_id": "123",
    }


class RecordingTFAPI:
    def __init__(self, document=None, error=None):
        self.document = document or {"data": [], "included": []}
        self.error = error
        self.calls = []

    def list_builds(self, app_id, **params):
        self.calls.append(("list_builds", app_id, params))
        if self.error is not None:
            raise self.error
        return self.document

    def list_beta_groups(self, app_id):
        self.calls.append(("list_beta_groups", app_id))
        return []

    def _get_paginated_data(self, path, **params):
        raise AssertionError("App Store versions must not be queried")


def test_query_testflight_uses_builds_include(tmp_path: Path):
    api = GroupFirstAPI()
    created = []

    def factory(issuer_id, key_id, key_file):
        created.append((issuer_id, key_id, key_file))
        return api

    outcome = query_testflight(
        "myapp",
        profile_lookup=lambda name: _creds(tmp_path),
        api_factory=factory,
        guard=lambda profile, creds: None,
    )
    assert created
    names = [call[0] for call in api.calls]
    assert names[0] == "list_beta_groups"
    assert "list_beta_group_builds" in names
    assert outcome.query_error == ""
    assert "TF 321（Public）" in outcome.last_result
    assert outcome.snapshot is not None
    assert outcome.snapshot.watch == "testflight"


def test_query_review_dispatches_testflight_watch(tmp_path: Path):
    api = GroupFirstAPI()
    outcome = query_review(
        "myapp",
        profile_lookup=lambda name: _creds(tmp_path),
        api_factory=lambda *args: api,
        guard=lambda profile, creds: None,
        watch="testflight",
    )
    assert outcome.last_result.startswith("TF 321")
    assert api.calls[0][0] == "list_beta_groups"
    assert not any("appStoreVersions" in str(call) for call in api.calls)


class GroupFirstAPI:
    """Apple-shaped fake: group membership is on GET /v1/betaGroups/{id}/builds.

    App-wide GET /v1/builds does not include betaGroups linkage (sparse
    fields[builds] / empty relationship), which is the live ASC shape that
    made the old include-only fetch look successful while returning nothing.
    """

    def __init__(self, *, groups=None, group_builds=None, hydrate=None, submissions=None, details=None):
        self.calls = []
        self.groups = groups if groups is not None else [
            {"id": "g-int", "type": "betaGroups", "attributes": {"name": "QA", "isInternalGroup": True}},
            {"id": "g-ext", "type": "betaGroups", "attributes": {"name": "Public", "isInternalGroup": False}},
        ]
        self.group_builds = group_builds if group_builds is not None else {
            "g-ext": {
                "data": [
                    {
                        "type": "builds",
                        "id": "b1",
                        "attributes": {
                            "version": "321",
                            "expired": False,
                            "uploadedDate": "2026-10-14T01:00:00Z",
                        },
                    }
                ],
                "included": [],
            }
        }
        self.hydrate = hydrate
        self.submissions = submissions if submissions is not None else {
            "b1": [{"id": "s1", "attributes": {"betaReviewState": "WAITING_FOR_REVIEW"}}]
        }
        self.details = details if details is not None else {
            "b1": {
                "id": "d1",
                "attributes": {"externalBuildState": "WAITING_FOR_BETA_REVIEW"},
            }
        }

    def list_beta_groups(self, app_id, **params):
        self.calls.append(("list_beta_groups", app_id, params))
        return self.groups

    def list_beta_group_builds(self, group_id, **params):
        self.calls.append(("list_beta_group_builds", group_id, params))
        return self.group_builds.get(group_id, {"data": [], "included": []})

    def list_builds(self, app_id, **params):
        self.calls.append(("list_builds", app_id, params))
        if self.hydrate is not None:
            return self.hydrate
        # Default: no relationship linkage (real ASC when fields[builds]
        # omits betaGroups / betaAppReviewSubmission / buildBetaDetail).
        return {
            "data": [
                {
                    "type": "builds",
                    "id": "b1",
                    "attributes": {"version": "321", "expired": False},
                }
            ],
            "included": [],
        }

    def list_beta_app_review_submissions(self, build_id):
        self.calls.append(("list_beta_app_review_submissions", build_id))
        return list(self.submissions.get(build_id, []))

    def get_build_beta_detail(self, build_id):
        self.calls.append(("get_build_beta_detail", build_id))
        return self.details.get(build_id)

    def _get_paginated_data(self, path, **params):
        raise AssertionError(path)


def _fetch_builds(api, app_id="app-1"):
    result = fetch_testflight_builds(api, app_id)
    return result.builds if hasattr(result, "builds") else result


def test_fetch_uses_external_group_builds_not_app_wide_include():
    api = GroupFirstAPI()
    result = fetch_testflight_builds(api, "app-1")
    builds = result.builds if hasattr(result, "builds") else result
    names = [call[0] for call in api.calls]
    assert "list_beta_groups" in names
    assert ("list_beta_group_builds", "g-ext") in [
        (call[0], call[1]) for call in api.calls if call[0] == "list_beta_group_builds"
    ]
    assert "g-int" not in [
        call[1] for call in api.calls if call[0] == "list_beta_group_builds"
    ]
    assert [item.version for item in builds] == ["321"]
    assert builds[0].external_groups == ["Public"]
    assert builds[0].beta_review_state == "WAITING_FOR_REVIEW"
    assert builds[0].external_build_state == "WAITING_FOR_BETA_REVIEW"
    assert not any(call[0] == "_get_paginated_data" for call in api.calls)


def test_fetch_falls_back_to_submission_and_build_beta_detail():
    api = GroupFirstAPI(hydrate={"data": [{"type": "builds", "id": "b1", "attributes": {"version": "321"}}], "included": []})
    builds = _fetch_builds(api)
    assert ("list_beta_app_review_submissions", "b1") in api.calls
    assert ("get_build_beta_detail", "b1") in api.calls
    assert builds[0].beta_review_state == "WAITING_FOR_REVIEW"
    assert builds[0].external_build_state == "WAITING_FOR_BETA_REVIEW"


def test_fetch_unsubmitted_when_no_submission_resource():
    api = GroupFirstAPI(submissions={"b1": []}, details={"b1": {"id": "d1", "attributes": {"externalBuildState": "READY_FOR_BETA_SUBMISSION"}}})
    builds = _fetch_builds(api)
    assert builds[0].beta_review_state == ""
    assert builds[0].has_submission is False
    assert builds[0].external_build_state == "READY_FOR_BETA_SUBMISSION"
    in_review, ready = classify_testflight_builds(builds)
    assert in_review == [("321（Public）", "未送审")]
    assert ready == []


def test_fetch_empty_reason_without_external_groups():
    api = GroupFirstAPI(
        groups=[{"id": "g-int", "attributes": {"name": "QA", "isInternalGroup": True}}],
        group_builds={},
    )
    result = fetch_testflight_builds(api, "app-1")
    assert hasattr(result, "empty_reason")
    assert result.empty_reason == "no_external_groups"
    assert result.builds == []
    assert not any(call[0] == "list_beta_group_builds" for call in api.calls)


def test_fetch_empty_reason_without_group_builds():
    api = GroupFirstAPI(group_builds={"g-ext": {"data": [], "included": []}})
    result = fetch_testflight_builds(api, "app-1")
    assert result.empty_reason == "no_builds"
    assert result.builds == []


def test_hydrate_fields_keep_review_relationships():
    api = GroupFirstAPI(
        hydrate=_document(_build("b1", "321", groups=["Public"])),
        submissions={"b1": []},
        details={},
    )
    _fetch_builds(api)
    hydrate = [call for call in api.calls if call[0] == "list_builds"]
    assert hydrate
    params = hydrate[0][2]
    assert "b1" in params.get("filter[id]", "")
    fields = params.get("fields[builds]", "")
    assert "betaAppReviewSubmission" in fields
    assert "buildBetaDetail" in fields


def test_list_beta_group_builds_endpoint(api):
    with patch.object(
        api,
        "get",
        return_value={
            "data": [{"type": "builds", "id": "b1", "attributes": {"version": "9"}}],
            "links": {},
        },
    ) as mock_get:
        document = api.list_beta_group_builds("g-ext")
    assert document["data"][0]["id"] == "b1"
    assert mock_get.call_args == call(
        "/v1/betaGroups/g-ext/builds",
        **{"limit": 200},
    )


def test_testflight_403_hints_missing_permission(api):
    class Resp:
        status_code = 403
        headers = {}
        text = ""

        def json(self):
            return {"errors": [{"detail": "The request is forbidden.", "title": "FORBIDDEN"}]}

    with patch("asc.api.requests.request", return_value=Resp()):
        with pytest.raises(Exception) as exc:
            api.list_beta_groups("app-1")
    message = str(exc.value)
    assert "[403]" in message
    assert "TestFlight" in message or "权限" in message


def test_query_testflight_uses_group_builds(tmp_path: Path):
    api = GroupFirstAPI()
    outcome = query_testflight(
        "myapp",
        profile_lookup=lambda name: _creds(tmp_path),
        api_factory=lambda *args: api,
        guard=lambda profile, creds: None,
    )
    assert any(call[0] == "list_beta_group_builds" for call in api.calls)
    assert outcome.query_error == ""
    assert "TF 321（Public）" in outcome.last_result
    assert "等待 Beta 审核" in outcome.last_result
    assert outcome.snapshot.watch == "testflight"


def test_query_testflight_explains_missing_external_groups(tmp_path: Path):
    api = GroupFirstAPI(
        groups=[{"id": "g-int", "attributes": {"name": "QA", "isInternalGroup": True}}],
        group_builds={},
    )
    outcome = query_testflight(
        "myapp",
        profile_lookup=lambda name: _creds(tmp_path),
        api_factory=lambda *args: api,
        guard=lambda profile, creds: None,
    )
    assert outcome.query_error == ""
    assert "外部" in outcome.last_result
    assert "组" in outcome.last_result
    assert outcome.snapshot.watch == "testflight"
    assert outcome.snapshot.in_review == []
