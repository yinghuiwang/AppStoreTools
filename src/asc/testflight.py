"""Read-only TestFlight external-group Beta Review helpers."""

from __future__ import annotations

from typing import Optional

TF_BUILD_INCLUDES = "betaAppReviewSubmission,buildBetaDetail,betaGroups"

IN_TF_REVIEW_LABELS = {
    "WAITING_FOR_BETA_REVIEW": "等待 Beta 审核",
    "IN_BETA_REVIEW": "Beta 审核中",
    "BETA_APPROVED": "Beta 已通过",
    "BETA_REJECTED": "Beta 被拒",
}

BETA_REVIEW_FALLBACK_LABELS = {
    "WAITING_FOR_REVIEW": "等待 Beta 审核",
    "IN_REVIEW": "Beta 审核中",
    "APPROVED": "Beta 已通过",
    "REJECTED": "Beta 被拒",
}

TF_READY_STATES = frozenset({"READY_FOR_BETA_TESTING", "IN_BETA_TESTING"})


class TestFlightBuild:
    __test__ = False

    def __init__(
        self,
        build_id: str,
        version: str,
        expired: bool,
        uploaded_date: str,
        beta_review_state: str,
        external_build_state: str,
        external_groups: list,
        unresolved_group_ids: Optional[list] = None,
    ) -> None:
        self.build_id = build_id
        self.version = version
        self.expired = expired
        self.uploaded_date = uploaded_date
        self.beta_review_state = beta_review_state
        self.external_build_state = external_build_state
        self.external_groups = list(external_groups)
        self.unresolved_group_ids = list(unresolved_group_ids or [])

    @property
    def has_external_group(self) -> bool:
        return bool(self.external_groups)


def _attr_text(attributes: dict, key: str) -> str:
    raw = attributes.get(key)
    return raw.strip() if isinstance(raw, str) else ""


def _rel_data(resource: dict, name: str):
    relationships = resource.get("relationships")
    if not isinstance(relationships, dict):
        return None
    rel = relationships.get(name)
    if not isinstance(rel, dict):
        return None
    return rel.get("data")


def _index_included(included) -> dict:
    index = {}
    for item in included or []:
        if not isinstance(item, dict):
            continue
        type_ = item.get("type")
        ident = item.get("id")
        if type_ and ident:
            index[(type_, ident)] = item
    return index


def _group_refs(resource: dict) -> list:
    raw = _rel_data(resource, "betaGroups")
    if raw is None:
        return []
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    return []


def parse_testflight_builds(document: dict) -> list:
    """Parse a builds JSON:API document (data + included) into builds."""
    if not isinstance(document, dict):
        return []
    index = _index_included(document.get("included"))
    builds = []
    seen = set()
    for item in document.get("data") or []:
        if not isinstance(item, dict) or item.get("type") != "builds":
            continue
        build_id = item.get("id") or ""
        if build_id:
            if build_id in seen:
                continue
            seen.add(build_id)
        attributes = item.get("attributes") or {}
        if not isinstance(attributes, dict):
            attributes = {}
        submission = _rel_data(item, "betaAppReviewSubmission")
        detail = _rel_data(item, "buildBetaDetail")
        beta_review_state = ""
        if isinstance(submission, dict) and submission.get("id"):
            included = index.get(("betaAppReviewSubmissions", submission["id"]))
            if included:
                beta_review_state = _attr_text(
                    included.get("attributes") or {}, "betaReviewState"
                )
        external_build_state = ""
        if isinstance(detail, dict) and detail.get("id"):
            included = index.get(("buildBetaDetails", detail["id"]))
            if included:
                external_build_state = _attr_text(
                    included.get("attributes") or {}, "externalBuildState"
                )
        external_groups = []
        unresolved = []
        for ref in _group_refs(item):
            group_id = ref.get("id") or ""
            if not group_id:
                continue
            included = index.get(("betaGroups", group_id))
            if not included:
                unresolved.append(group_id)
                continue
            group_attrs = included.get("attributes") or {}
            if not isinstance(group_attrs, dict):
                unresolved.append(group_id)
                continue
            if group_attrs.get("isInternalGroup") is not False:
                continue
            name = _attr_text(group_attrs, "name") or group_id
            if name not in external_groups:
                external_groups.append(name)
        builds.append(
            TestFlightBuild(
                build_id=str(build_id),
                version=_attr_text(attributes, "version"),
                expired=bool(attributes.get("expired")),
                uploaded_date=_attr_text(attributes, "uploadedDate"),
                beta_review_state=beta_review_state,
                external_build_state=external_build_state,
                external_groups=external_groups,
                unresolved_group_ids=unresolved,
            )
        )
    return builds


def apply_beta_groups(builds: list, groups: list) -> list:
    """Fill unresolved group ids from a /v1/betaGroups payload."""
    by_id = {}
    for item in groups or []:
        if not isinstance(item, dict):
            continue
        ident = item.get("id")
        if not ident:
            continue
        by_id[ident] = item.get("attributes") or {}
    for build in builds:
        leftover = []
        for group_id in build.unresolved_group_ids:
            attrs = by_id.get(group_id)
            if not isinstance(attrs, dict):
                leftover.append(group_id)
                continue
            if attrs.get("isInternalGroup") is not False:
                continue
            name = _attr_text(attrs, "name") or group_id
            if name not in build.external_groups:
                build.external_groups.append(name)
        build.unresolved_group_ids = leftover
    return builds


def fetch_testflight_builds(api, app_id: str) -> list:
    """List builds once (with includes); only list groups if names are missing."""
    document = api.list_builds(
        app_id,
        include=TF_BUILD_INCLUDES,
        sort="-uploadedDate",
        **{
            "fields[builds]": "version,expired,processingState,uploadedDate",
            "fields[betaAppReviewSubmissions]": "betaReviewState",
            "fields[buildBetaDetails]": "externalBuildState,internalBuildState",
            "fields[betaGroups]": "name,isInternalGroup",
        },
    )
    builds = parse_testflight_builds(document)
    if any(item.unresolved_group_ids for item in builds):
        apply_beta_groups(builds, api.list_beta_groups(app_id))
    return builds


def tf_build_display_name(version: str, groups: list) -> str:
    text = version.strip() if isinstance(version, str) else ""
    name = text or "未知构建"
    if groups:
        return f"{name}（{'、'.join(groups)}）"
    return name


def classify_testflight_builds(builds: list) -> tuple:
    """Return ``(in_review, ready)`` rows for external-group builds."""
    seen = set()
    in_review = []
    ready = []
    for build in builds:
        if build.build_id:
            if build.build_id in seen:
                continue
            seen.add(build.build_id)
        if build.expired or not build.has_external_group:
            continue
        state = build.external_build_state
        label = IN_TF_REVIEW_LABELS.get(state)
        if label is None and not state:
            label = BETA_REVIEW_FALLBACK_LABELS.get(build.beta_review_state)
        name = tf_build_display_name(build.version, build.external_groups)
        if label:
            in_review.append((name, label))
        elif state in TF_READY_STATES:
            ready.append(name)
    if in_review:
        return in_review, []
    return [], ready
