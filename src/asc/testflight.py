"""Read-only TestFlight external-group Beta Review helpers."""

from __future__ import annotations

from typing import Optional

TF_REVIEW_INCLUDES = "betaAppReviewSubmission,buildBetaDetail"
TF_REVIEW_BUILD_FIELDS = (
    "version,expired,processingState,uploadedDate,"
    "betaAppReviewSubmission,buildBetaDetail"
)

# Kept for parsers/tests that still inspect include strings.
TF_BUILD_INCLUDES = "betaAppReviewSubmission,buildBetaDetail,betaGroups"

EMPTY_NO_EXTERNAL_GROUPS = "no_external_groups"
EMPTY_NO_BUILDS = "no_builds"

NOT_SUBMITTED_LABEL = "未送审"

IN_TF_REVIEW_LABELS = {
    "WAITING_FOR_BETA_REVIEW": "等待 Beta 审核",
    "IN_BETA_REVIEW": "Beta 审核中",
    "BETA_APPROVED": "Beta 已通过",
    "BETA_REJECTED": "Beta 被拒",
    "READY_FOR_BETA_SUBMISSION": NOT_SUBMITTED_LABEL,
    "MISSING_EXPORT_COMPLIANCE": "缺少出口合规",
    "PROCESSING": "处理中",
    "PROCESSING_EXCEPTION": "处理异常",
}

BETA_REVIEW_FALLBACK_LABELS = {
    "WAITING_FOR_REVIEW": "等待 Beta 审核",
    "IN_REVIEW": "Beta 审核中",
    "APPROVED": "Beta 已通过",
    "REJECTED": "Beta 被拒",
}

TF_READY_STATES = frozenset({"READY_FOR_BETA_TESTING", "IN_BETA_TESTING"})

# Empty / not-submitted / still-processing: keep walking to a smaller build.
_SKIP_EXTERNAL_STATES = frozenset({"", "PROCESSING", "READY_FOR_BETA_SUBMISSION"})

_HYDRATE_CHUNK = 40


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
        has_submission: bool = False,
    ) -> None:
        self.build_id = build_id
        self.version = version
        self.expired = expired
        self.uploaded_date = uploaded_date
        self.beta_review_state = beta_review_state
        self.external_build_state = external_build_state
        self.external_groups = list(external_groups)
        self.unresolved_group_ids = list(unresolved_group_ids or [])
        self.has_submission = bool(has_submission)

    @property
    def has_external_group(self) -> bool:
        return bool(self.external_groups)


class TestFlightFetchResult:
    __test__ = False

    def __init__(
        self,
        builds: list,
        *,
        external_groups: Optional[list] = None,
        empty_reason: str = "",
    ) -> None:
        self.builds = list(builds)
        self.external_groups = list(external_groups or [])
        self.empty_reason = empty_reason or ""


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


def _is_internal_group(attrs: dict) -> bool:
    return attrs.get("isInternalGroup") is True


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
        has_submission = False
        if isinstance(submission, dict) and submission.get("id"):
            has_submission = True
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
            if _is_internal_group(group_attrs):
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
                has_submission=has_submission,
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
            if _is_internal_group(attrs):
                continue
            name = _attr_text(attrs, "name") or group_id
            if name not in build.external_groups:
                build.external_groups.append(name)
        build.unresolved_group_ids = leftover
    return builds


def _split_groups(groups: list) -> list:
    """Return ``[(id, name), ...]`` for groups that are not internal."""
    external = []
    for item in groups or []:
        if not isinstance(item, dict):
            continue
        ident = item.get("id")
        if not ident:
            continue
        attrs = item.get("attributes") or {}
        if not isinstance(attrs, dict):
            attrs = {}
        if _is_internal_group(attrs):
            continue
        name = _attr_text(attrs, "name") or ident
        external.append((ident, name))
    return external


def _chunks(items: list, size: int = _HYDRATE_CHUNK):
    for index in range(0, len(items), size):
        yield items[index : index + size]


def _apply_review_document(by_id: dict, document: dict) -> None:
    for item in parse_testflight_builds(document):
        target = by_id.get(item.build_id)
        if target is None:
            continue
        if item.version and not target.version:
            target.version = item.version
        if item.uploaded_date and not target.uploaded_date:
            target.uploaded_date = item.uploaded_date
        target.expired = target.expired or item.expired
        if item.beta_review_state:
            target.beta_review_state = item.beta_review_state
        if item.has_submission:
            target.has_submission = True
        if item.external_build_state:
            target.external_build_state = item.external_build_state


def _fill_missing_review_from_endpoints(api, builds: list) -> None:
    """GET submissions + buildBetaDetail when include did not hydrate states."""
    for build in builds:
        if not build.beta_review_state:
            submissions = api.list_beta_app_review_submissions(build.build_id)
            if submissions:
                first = submissions[0] if isinstance(submissions[0], dict) else {}
                attrs = first.get("attributes") or {}
                if not isinstance(attrs, dict):
                    attrs = {}
                build.beta_review_state = _attr_text(attrs, "betaReviewState")
                build.has_submission = True
            else:
                build.has_submission = False
        else:
            build.has_submission = True
        if not build.external_build_state:
            detail = api.get_build_beta_detail(build.build_id)
            if isinstance(detail, dict):
                attrs = detail.get("attributes") or {}
                if not isinstance(attrs, dict):
                    attrs = {}
                build.external_build_state = _attr_text(attrs, "externalBuildState")


def _hydrate_review_states(api, app_id: str, builds: list) -> None:
    ids = [item.build_id for item in builds if item.build_id]
    by_id = {item.build_id: item for item in builds if item.build_id}
    for chunk in _chunks(ids):
        document = api.list_builds(
            app_id,
            include=TF_REVIEW_INCLUDES,
            **{
                "filter[id]": ",".join(chunk),
                "fields[builds]": TF_REVIEW_BUILD_FIELDS,
                "fields[betaAppReviewSubmissions]": "betaReviewState",
                "fields[buildBetaDetails]": "externalBuildState,internalBuildState",
            },
        )
        _apply_review_document(by_id, document)
    _fill_missing_review_from_endpoints(api, builds)


def _build_number_key(version: str) -> tuple:
    """Numeric build order: 100 > 99 > 9. Non-numeric versions sort last."""
    text = version.strip() if isinstance(version, str) else ""
    if text.isdigit():
        return (1, int(text), text)
    return (0, 0, text)


def has_review_status(build) -> bool:
    """True when Beta Review or a meaningful externalBuildState is present."""
    review = build.beta_review_state.strip() if isinstance(build.beta_review_state, str) else ""
    if review:
        return True
    state = (
        build.external_build_state.strip()
        if isinstance(build.external_build_state, str)
        else ""
    )
    return state not in _SKIP_EXTERNAL_STATES


def _copy_build_for_group(build, group_name: str):
    return TestFlightBuild(
        build_id=build.build_id,
        version=build.version,
        expired=build.expired,
        uploaded_date=build.uploaded_date,
        beta_review_state=build.beta_review_state,
        external_build_state=build.external_build_state,
        external_groups=[group_name],
        unresolved_group_ids=list(build.unresolved_group_ids),
        has_submission=build.has_submission,
    )


def _merge_selected_group_builds(pairs: list) -> list:
    selected = []
    by_id = {}
    for group_name, build in pairs:
        if build.build_id and build.build_id in by_id:
            existing = by_id[build.build_id]
            if group_name not in existing.external_groups:
                existing.external_groups.append(group_name)
            continue
        copied = _copy_build_for_group(build, group_name)
        selected.append(copied)
        if copied.build_id:
            by_id[copied.build_id] = copied
    return selected


def _members_by_group(builds: list) -> dict:
    by_group: dict = {}
    for build in builds:
        for name in build.external_groups:
            by_group.setdefault(name, []).append(build)
    return by_group


def _group_names_in_order(builds: list, group_names=None) -> list:
    if group_names is not None:
        return list(group_names)
    order = []
    for build in builds:
        for name in build.external_groups:
            if name not in order:
                order.append(name)
    return order


def _pick_current_group_build(members: list, is_current) -> Optional[object]:
    ordered = sorted(members, key=lambda item: _build_number_key(item.version), reverse=True)
    for build in ordered:
        if build.expired:
            continue
        if is_current(build):
            return build
    return next((item for item in ordered if not item.expired), None) or (
        ordered[0] if ordered else None
    )


def select_current_builds_by_group(builds: list, group_names=None) -> list:
    """Keep at most one build per external group.

    Walks build numbers from large to small and stops at the first build
    with a review status. Groups with only empty / PROCESSING / 未送审
    builds keep the highest-number candidate so callers can show 未送审
    once instead of every historical row.
    """
    by_group = _members_by_group(builds)
    pairs = []
    for name in _group_names_in_order(builds, group_names):
        members = by_group.get(name) or []
        if not members:
            continue
        chosen = _pick_current_group_build(members, has_review_status)
        if chosen is not None:
            pairs.append((name, chosen))
    return _merge_selected_group_builds(pairs)


def _hydrate_and_select_current(api, app_id: str, builds: list, group_names: list) -> list:
    """Hydrate review state from newest build downward; stop per group."""
    by_group = _members_by_group(builds)
    hydrated = set()

    def ensure_current(build) -> bool:
        ident = build.build_id
        if ident and ident not in hydrated:
            _hydrate_review_states(api, app_id, [build])
            hydrated.add(ident)
        return has_review_status(build)

    pairs = []
    for name in group_names:
        members = by_group.get(name) or []
        if not members:
            continue
        chosen = _pick_current_group_build(members, ensure_current)
        if chosen is None:
            continue
        ident = chosen.build_id
        if ident and ident not in hydrated:
            _hydrate_review_states(api, app_id, [chosen])
            hydrated.add(ident)
        pairs.append((name, chosen))
    return _merge_selected_group_builds(pairs)


def fetch_testflight_builds(api, app_id: str) -> TestFlightFetchResult:
    """Load each external group's current Beta Review build.

    Membership comes from ``GET /v1/betaGroups`` +
    ``GET /v1/betaGroups/{id}/builds``. Builds are sorted by numeric
    version (100 > 99 > 9); review state is hydrated from newest to
    oldest until the first build with a review status is found. Each
    external group contributes at most one row.

    Review state comes from
    ``GET /v1/builds?include=betaAppReviewSubmission,buildBetaDetail``
    (relationship names must be in ``fields[builds]``) and, if include is
    empty, from ``GET /v1/betaAppReviewSubmissions`` and
    ``GET /v1/builds/{id}/buildBetaDetail``.
    """
    groups = api.list_beta_groups(
        app_id,
        **{"fields[betaGroups]": "name,isInternalGroup"},
    )
    external = _split_groups(groups)
    if not external:
        return TestFlightFetchResult(
            [],
            external_groups=[],
            empty_reason=EMPTY_NO_EXTERNAL_GROUPS,
        )

    by_id: dict = {}
    for group_id, group_name in external:
        document = api.list_beta_group_builds(
            group_id,
            **{"fields[builds]": "version,expired,processingState,uploadedDate"},
        )
        if isinstance(document, dict):
            rows = document.get("data") or []
        elif isinstance(document, list):
            rows = document
        else:
            rows = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            if item.get("type") not in (None, "builds"):
                continue
            build_id = str(item.get("id") or "")
            if not build_id:
                continue
            attributes = item.get("attributes") or {}
            if not isinstance(attributes, dict):
                attributes = {}
            existing = by_id.get(build_id)
            if existing is None:
                by_id[build_id] = TestFlightBuild(
                    build_id=build_id,
                    version=_attr_text(attributes, "version"),
                    expired=bool(attributes.get("expired")),
                    uploaded_date=_attr_text(attributes, "uploadedDate"),
                    beta_review_state="",
                    external_build_state="",
                    external_groups=[group_name],
                    has_submission=False,
                )
            elif group_name not in existing.external_groups:
                existing.external_groups.append(group_name)

    builds = list(by_id.values())
    names = [name for _, name in external]
    if not builds:
        return TestFlightFetchResult(
            [],
            external_groups=names,
            empty_reason=EMPTY_NO_BUILDS,
        )
    current = _hydrate_and_select_current(api, app_id, builds, names)
    return TestFlightFetchResult(current, external_groups=names, empty_reason="")


def tf_build_display_name(version: str, groups: list) -> str:
    text = version.strip() if isinstance(version, str) else ""
    name = text or "未知构建"
    if groups:
        return f"{name}（{'、'.join(groups)}）"
    return name


def classify_testflight_builds(builds: list) -> tuple:
    """Return ``(in_review, ready)`` rows for each group's current build."""
    seen = set()
    in_review = []
    ready = []
    for build in select_current_builds_by_group(builds):
        if build.build_id:
            if build.build_id in seen:
                continue
            seen.add(build.build_id)
        if not build.has_external_group:
            continue
        name = tf_build_display_name(build.version, build.external_groups)
        if not has_review_status(build):
            in_review.append((name, NOT_SUBMITTED_LABEL))
            continue
        if build.expired:
            continue
        state = build.external_build_state
        label = IN_TF_REVIEW_LABELS.get(state)
        if label is None and not state:
            label = BETA_REVIEW_FALLBACK_LABELS.get(build.beta_review_state)
        if label is None and state not in TF_READY_STATES:
            if not build.has_submission and not build.beta_review_state:
                label = NOT_SUBMITTED_LABEL
        if label:
            in_review.append((name, label))
        elif state in TF_READY_STATES:
            ready.append(name)
    if in_review:
        return in_review, []
    return [], ready
