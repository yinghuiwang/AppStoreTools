"""Rerun a failed Web task from its sanitized replay snapshot.

``rerun_task`` is server-only: it is not a model tool. Callers (the apply
route) invoke it after ``apply_fix`` fully succeeds, the request asked for
``rerun=true``, and the plan includes a ``rerun`` payload.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Callable, Iterator

from asc.web.tasks import TaskStore

_STORE_LOCK = threading.Lock()


class RerunError(Exception):
    """Replay is missing or the kind cannot be restarted."""

    def __init__(self, code: str = "no_replay") -> None:
        self.code = code
        super().__init__(code)


def rerun_task(original_task_id: str, *, task_store: TaskStore) -> str:
    """Start a new task from ``original_task_id``'s replay. Old row stays as-is."""
    replay = task_store.get_replay(original_task_id)
    if not isinstance(replay, dict):
        raise RerunError("no_replay")
    kind = replay.get("kind")
    dispatcher = _DISPATCH.get(kind)
    if dispatcher is None:
        raise RerunError("no_replay")
    with _bind_web_task_store(task_store):
        return dispatcher(replay)


def _params(replay: dict[str, Any]) -> dict[str, Any]:
    params = replay.get("params")
    return params if isinstance(params, dict) else {}


def _profile(replay: dict[str, Any]) -> str:
    return str(replay.get("profile") or "")


def _verbose(replay: dict[str, Any]) -> bool:
    return bool(replay.get("verbose"))


@contextmanager
def _bind_web_task_store(task_store: TaskStore) -> Iterator[None]:
    """Point Web starters at the given store so create/replay stay together.

    Production apply routes pass the process singleton, so this swap is a
    no-op there. Tests pass a temp store; ``start_background_task`` is mocked
    so starter ``run()`` closures never execute against the restored global.
    """
    from asc.web import routes_api, routes_iap, routes_listing

    with _STORE_LOCK:
        prev_api = routes_api._task_store
        prev_iap = routes_iap._task_store
        prev_listing = routes_listing.task_store
        routes_api._task_store = task_store
        routes_iap._task_store = task_store
        routes_listing.task_store = task_store
        try:
            yield
        finally:
            routes_api._task_store = prev_api
            routes_iap._task_store = prev_iap
            routes_listing.task_store = prev_listing


def _rerun_metadata(replay: dict[str, Any]) -> str:
    from asc.web.routes_api import _start_metadata_task

    params = _params(replay)
    return _start_metadata_task(
        profile=_profile(replay),
        csv_path=str(params.get("csv_path") or ""),
        screenshots_dir=str(params.get("screenshots_dir") or ""),
        include_metadata=bool(params.get("include_metadata", True)),
        include_screenshots=bool(params.get("include_screenshots", False)),
        dry_run=bool(params.get("dry_run", False)),
        verbose=_verbose(replay),
        locales=params.get("locales"),
        fields_by_locale=params.get("fields_by_locale"),
        screenshot_scopes=params.get("screenshot_scopes"),
    )


def _rerun_build(replay: dict[str, Any]) -> str:
    from asc.web.routes_api import _start_build_task

    params = _params(replay)
    signing = params.get("signing") if params.get("signing") in {"auto", "manual"} else "auto"
    return _start_build_task(
        profile=_profile(replay),
        mode=str(params.get("mode") or "build"),
        project=str(params.get("project") or ""),
        scheme=str(params.get("scheme") or ""),
        destination=str(params.get("destination") or ""),
        ipa_path=str(params.get("ipa_path") or ""),
        verbose=_verbose(replay),
        signing=signing,
        dry_run=bool(params.get("dry_run", False)),
        reuse_archive=str(params.get("reuse_archive") or ""),
    )


def _rerun_iap(replay: dict[str, Any]) -> str:
    from asc.web.routes_iap import _start_iap_task

    params = _params(replay)
    return _start_iap_task(
        _profile(replay),
        str(params.get("iap_file") or ""),
        bool(params.get("dry_run", False)),
        bool(params.get("update_existing", False)),
        _verbose(replay),
    )


def _rerun_iap_review_screenshots(replay: dict[str, Any]) -> str:
    from asc.commands.iap_review_screenshots import ReviewScreenshotUploadItem
    from asc.web.routes_iap import _start_iap_review_screenshots_task

    params = _params(replay)
    items: list[ReviewScreenshotUploadItem] = []
    raw_items = params.get("items")
    if isinstance(raw_items, list):
        for row in raw_items:
            if not isinstance(row, dict):
                continue
            items.append(
                ReviewScreenshotUploadItem(
                    kind=str(row.get("kind") or ""),
                    id=str(row.get("id") or ""),
                    product_id=str(row.get("productId") or row.get("product_id") or ""),
                    path=str(row.get("path") or ""),
                )
            )
    return _start_iap_review_screenshots_task(
        _profile(replay),
        items,
        bool(params.get("dry_run", False)),
        _verbose(replay),
    )


def _rerun_whats_new(replay: dict[str, Any]) -> str:
    from asc.web.routes_api import _start_whats_new_task

    params = _params(replay)
    return _start_whats_new_task(
        _profile(replay),
        bool(params.get("dry_run", False)),
        translations=params.get("translations"),
        text=params.get("text"),
        locales=params.get("locales"),
        translate=bool(params.get("translate", False)),
        source_locale=str(params.get("source_locale") or "auto"),
        verbose=_verbose(replay),
    )


def _rerun_whats_new_translate(replay: dict[str, Any]) -> str:
    from asc.web.routes_api import _start_whats_new_translate_task

    params = _params(replay)
    return _start_whats_new_translate_task(
        _profile(replay),
        str(params.get("text") or ""),
        str(params.get("source_locale") or "auto"),
        _verbose(replay),
    )


def _rerun_urls(replay: dict[str, Any]) -> str:
    from asc.web.routes_api import _start_urls_task

    params = _params(replay)
    locales = params.get("locales")
    return _start_urls_task(
        profile=_profile(replay),
        field=str(params.get("field") or ""),
        url=str(params.get("url") or ""),
        locales=list(locales) if isinstance(locales, list) else [],
        dry_run=bool(params.get("dry_run", False)),
        verbose=_verbose(replay),
    )


def _rerun_update(replay: dict[str, Any]) -> str:
    from asc.web.routes_api import _start_update_task

    params = _params(replay)
    version = params.get("version") or None
    branch = params.get("branch") or None
    if version == "":
        version = None
    if branch == "":
        branch = None
    return _start_update_task(
        version=version,
        branch=branch,
        verbose=_verbose(replay),
    )


def _rerun_listing_pull_screenshots(replay: dict[str, Any]) -> str:
    from asc.web.routes_listing import _start_listing_pull_screenshots_task

    params = _params(replay)
    scopes = params.get("scopes")
    return _start_listing_pull_screenshots_task(
        _profile(replay),
        str(params.get("screenshots_dir") or ""),
        list(scopes) if isinstance(scopes, list) else [],
    )


_DISPATCH: dict[str, Callable[[dict[str, Any]], str]] = {
    "metadata": _rerun_metadata,
    "build": _rerun_build,
    "iap": _rerun_iap,
    "iap-review-screenshots": _rerun_iap_review_screenshots,
    "whats-new": _rerun_whats_new,
    "whats-new-translate": _rerun_whats_new_translate,
    "urls": _rerun_urls,
    "update": _rerun_update,
    "listing-pull-screenshots": _rerun_listing_pull_screenshots,
}
