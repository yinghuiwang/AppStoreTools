"""Vue task pages keep the config form and the run panel mutually exclusive."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "src"

PAGES = (
    FRONTEND / "views/BuildView.vue",
    FRONTEND / "views/IapView.vue",
    FRONTEND / "views/WhatsNewView.vue",
    FRONTEND / "views/UrlsView.vue",
    FRONTEND / "views/listing/UploadTab.vue",
)


def _script_setup(src: str) -> str:
    return src.split("</script>", 1)[0]


def _on_mounted_source(src: str) -> str:
    script = _script_setup(src)
    idx = script.rfind("onMounted")
    return script[idx:] if idx >= 0 else ""


def test_use_task_page_phase_is_module_scoped_not_pinia():
    src = (FRONTEND / "composables/useTaskPagePhase.ts").read_text(encoding="utf-8")
    assert "Record<TaskPageId, PageBucket>" in src
    assert "sessionStorage" in src
    assert "function enterRun" in src
    assert "function backToForm" in src
    assert "export function resetTaskPageState" in src
    assert "export function bindTaskPageProfile" in src
    assert "pinia" not in src.lower()
    assert "defineStore" not in src


def test_task_pages_form_and_run_are_exclusive():
    for path in PAGES:
        src = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT)
        assert "useTaskPagePhase" in src, rel
        assert re.search(r"enterRun\(\s*task_id", src), rel
        assert "backToForm" in src, rel
        assert 'v-if="isForm"' in src, rel
        assert 'v-if="isRun && taskId"' in src, rel
        assert "enterRun" not in _on_mounted_source(src), rel


def test_deep_links_prefill_form_without_entering_run():
    build = (FRONTEND / "views/BuildView.vue").read_text(encoding="utf-8")
    upload = (FRONTEND / "views/listing/UploadTab.vue").read_text(encoding="utf-8")
    assert 'route.query.action === "build-upload"' in build
    assert "enterRun" not in _on_mounted_source(build)
    assert "route.query.action" in upload
    assert "enterRun" not in _on_mounted_source(upload)
    mounted = _on_mounted_source(upload)
    assert 'action === "all"' in mounted
    assert 'action === "metadata"' in mounted
    assert 'action === "screenshots"' in mounted


def test_task_run_bar_offers_back_to_form():
    src = (FRONTEND / "components/TaskRunBar.vue").read_text(encoding="utf-8")
    assert "task.back_to_form" in src
    assert "task.edit_and_rerun" in src
    assert 'emit("back")' in src or "emit('back')" in src
    assert "common.cancel_upload" in src


def test_task_run_bar_reuses_existing_sse():
    src = (FRONTEND / "components/TaskRunBar.vue").read_text(encoding="utf-8")
    assert "subscribeIfNeeded" in src
    log = (FRONTEND / "composables/useTaskLog.ts").read_text(encoding="utf-8")
    assert "function subscribeIfNeeded" in log
    assert "if (logTaskId.value === taskId) return" in log
    rail = (FRONTEND / "composables/useRightRail.ts").read_text(encoding="utf-8")
    assert "subscribeIfNeeded" in rail
