"""TaskReporter progress for What's New translate / upload phases."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from asc.commands.whats_new import (
    _upload_whats_new_locales,
    _whats_new_phase_plan,
    _whats_new_translate_locales,
)
from asc.reporting import TaskReporter


class RecordingSink:
    def __init__(self):
        self.logs = []
        self.progress_events = []

    def on_log(self, message, *, level="info"):
        self.logs.append((level, message))

    def on_progress(self, *, pct, msg, phase, phase_label, phase_index, phase_total):
        self.progress_events.append({
            "pct": pct,
            "msg": msg,
            "phase": phase,
            "phase_label": phase_label,
            "phase_index": phase_index,
            "phase_total": phase_total,
        })


def test_whats_new_phase_plan_translate_upload_60_40():
    assert _whats_new_phase_plan(translate=True, upload=True) == [
        ("translate", 60, "翻译"),
        ("upload", 40, "上传"),
    ]


def test_whats_new_phase_plan_preview_translate_only():
    assert _whats_new_phase_plan(translate=True, upload=False) == [
        ("translate", 100, "翻译"),
    ]


def test_whats_new_phase_plan_upload_only():
    assert _whats_new_phase_plan(translate=False, upload=True) == [
        ("upload", 100, "上传"),
    ]


def test_translate_and_upload_maps_to_60_40_pct():
    sink = RecordingSink()
    reporter = TaskReporter(sinks=[sink], verbose=False)
    reporter.set_phases(_whats_new_phase_plan(translate=True, upload=True))

    translator = MagicMock()
    translator.translate.side_effect = lambda text, locale, source: f"t-{locale}"

    reporter.phase("translate")
    translations, errors = _whats_new_translate_locales(
        translator,
        "Bug fixes.",
        ["zh-CN", "ja-JP"],
        "en-US",
        reporter=reporter,
    )
    assert errors == []
    assert set(translations) == {"zh-CN", "ja-JP"}

    translate_pcts = [e["pct"] for e in sink.progress_events if e["phase"] == "translate"]
    assert translate_pcts[-1] == 60

    api = MagicMock()
    ver_loc_map = {
        "zh-CN": {"id": "l-zh"},
        "ja-JP": {"id": "l-ja"},
    }
    reporter.phase("upload")
    _upload_whats_new_locales(
        api,
        ver_loc_map,
        translations,
        dry_run=False,
        reporter=reporter,
    )
    reporter.done("完成")

    pcts = [e["pct"] for e in sink.progress_events]
    assert pcts == sorted(pcts)
    assert pcts[-1] == 100
    upload_pcts = [e["pct"] for e in sink.progress_events if e["phase"] == "upload"]
    assert upload_pcts[0] == 60
    assert upload_pcts[-1] == 100


def test_presupplied_translations_upload_only_100():
    sink = RecordingSink()
    reporter = TaskReporter(sinks=[sink], verbose=False)
    reporter.set_phases(_whats_new_phase_plan(translate=False, upload=True))
    reporter.phase("upload")

    api = MagicMock()
    ver_loc_map = {
        "zh-CN": {"id": "l-zh"},
        "ja-JP": {"id": "l-ja"},
    }
    _upload_whats_new_locales(
        api,
        ver_loc_map,
        {"zh-CN": "你好", "ja-JP": "こんにちは"},
        dry_run=False,
        reporter=reporter,
    )
    reporter.done()

    phases = {e["phase"] for e in sink.progress_events}
    assert phases == {"upload"}
    assert sink.progress_events[-1]["pct"] == 100
    assert api.update_version_localization.call_count == 2


def test_failed_translate_locale_still_advances_progress():
    sink = RecordingSink()
    reporter = TaskReporter(sinks=[sink], verbose=False)
    reporter.set_phases(_whats_new_phase_plan(translate=True, upload=False))
    reporter.phase("translate")

    translator = MagicMock()

    def _side(text, locale, source):
        if locale == "zh-CN":
            raise RuntimeError("boom")
        return f"t-{locale}"

    translator.translate.side_effect = _side
    translations, errors = _whats_new_translate_locales(
        translator,
        "Bug fixes.",
        ["zh-CN", "ja-JP"],
        "en-US",
        reporter=reporter,
    )
    assert "ja-JP" in translations
    assert any("zh-CN" in e for e in errors)
    assert sink.progress_events[-1]["pct"] == 100
    joined = "\n".join(msg for _, msg in sink.logs)
    assert "zh-CN" in joined


def test_whats_new_source_has_no_progress_protocol():
    src = Path(__file__).resolve().parents[1] / "src" / "asc" / "commands" / "whats_new.py"
    assert "[PROGRESS:" not in src.read_text(encoding="utf-8")
