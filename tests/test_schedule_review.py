from datetime import datetime
from zoneinfo import ZoneInfo

from asc.schedule import (
    WATCH_TESTFLIGHT,
    ReviewSnapshot,
    build_failure_message,
    build_success_message,
    clamp_error,
    classify_versions,
    format_checked_at,
    format_last_result,
)


SH = ZoneInfo("Asia/Shanghai")


def version(vid, state, name="1.2.3", legacy=False):
    key = "appVersionState" if legacy else "appStoreState"
    return {"id": vid, "attributes": {key: state, "versionString": name}}


def test_in_review_excludes_prepare_and_on_sale():
    versions = [
        version("a", "PREPARE_FOR_SUBMISSION", "1.0.0"),
        version("b", "IN_REVIEW", "1.2.3"),
        version("c", "WAITING_FOR_REVIEW", "1.2.4"),
        version("d", "READY_FOR_SALE", "1.1.0"),
        version("e", "DEVELOPER_REJECTED", "1.0.9"),
        version("b", "REJECTED", "9.9.9"),
    ]
    snapshot = classify_versions(versions)
    assert snapshot.in_review == [("1.2.3", "审核中"), ("1.2.4", "等待审核")]
    assert snapshot.on_sale == []
    assert format_last_result(snapshot) == "1.2.3 审核中；1.2.4 等待审核"


def test_no_review_lists_ready_for_sale_in_api_order():
    versions = [
        version("a", "READY_FOR_SALE", "1.2.0"),
        version("b", "PREPARE_FOR_SUBMISSION", "9.0.0"),
        version("c", "READY_FOR_SALE", "1.1.0"),
        version("d", "DEVELOPER_REJECTED", "0.9.0"),
    ]
    snapshot = classify_versions(versions)
    assert format_last_result(snapshot) == "当前无在审版本；已上架 1.2.0、1.1.0"


def test_no_review_and_no_release():
    snapshot = classify_versions([version("a", "PREPARE_FOR_SUBMISSION", "1.0.0")])
    assert format_last_result(snapshot) == "当前无在审版本；暂无已上架版本"


def test_blank_version_and_state_key_rules():
    blank = version("a", "IN_REVIEW", "   ")
    assert classify_versions([blank]).in_review == [("未知版本", "审核中")]
    hidden = {
        "id": "b",
        "attributes": {"appStoreState": "", "appVersionState": "IN_REVIEW", "versionString": "8.0"},
    }
    legacy = version("c", "METADATA_REJECTED", "3.0", legacy=True)
    snapshot = classify_versions([hidden, legacy])
    assert snapshot.in_review == [("3.0", "被拒")]
    assert snapshot.on_sale == []


def test_empty_id_is_not_deduped():
    first = {"id": "", "attributes": {"appStoreState": "IN_REVIEW", "versionString": "1"}}
    second = {"id": "", "attributes": {"appStoreState": "REJECTED", "versionString": "2"}}
    snapshot = classify_versions([first, second])
    assert [item[0] for item in snapshot.in_review] == ["1", "2"]


def test_messages_use_profile_name_and_drop_seconds():
    now = datetime(2026, 10, 14, 9, 31, 45, tzinfo=SH)
    checked = format_checked_at(now, "Asia/Shanghai")
    assert checked == "2026-10-14 09:31（Asia/Shanghai）"
    reviewing = classify_versions([
        version("a", "IN_REVIEW", "1.2.3"),
        version("b", "WAITING_FOR_REVIEW", "1.2.4"),
    ])
    assert build_success_message("myapp", checked, reviewing) == (
        "应用：myapp\n"
        "监听：App Store 版本审核\n"
        "检查时间：2026-10-14 09:31（Asia/Shanghai）\n"
        "在审版本：\n"
        "- 1.2.3 审核中\n"
        "- 1.2.4 等待审核"
    )
    on_sale = classify_versions([version("a", "READY_FOR_SALE", "1.2.0")])
    assert build_success_message("myapp", checked, on_sale).endswith("已上架：1.2.0")
    empty = classify_versions([])
    assert build_success_message("myapp", checked, empty).endswith("已上架：暂无已上架版本")
    assert build_failure_message("myapp", checked, "凭证不完整") == (
        "应用：myapp\n"
        "监听：App Store 版本审核\n"
        "检查时间：2026-10-14 09:31（Asia/Shanghai）\n"
        "检查失败：凭证不完整"
    )


def test_testflight_messages_are_not_store_review():
    checked = "2026-10-14 09:31（Asia/Shanghai）"
    snapshot = ReviewSnapshot(
        [("123（External）", "等待 Beta 审核")],
        [],
        watch=WATCH_TESTFLIGHT,
    )
    assert format_last_result(snapshot) == "TF 123（External） 等待 Beta 审核"
    assert build_success_message("myapp", checked, snapshot) == (
        "应用：myapp\n"
        "监听：TestFlight 外部组版本审核\n"
        "检查时间：2026-10-14 09:31（Asia/Shanghai）\n"
        "TestFlight 外部组在审构建：\n"
        "- 123（External） 等待 Beta 审核"
    )
    idle = ReviewSnapshot([], ["120"], watch=WATCH_TESTFLIGHT)
    assert format_last_result(idle) == "当前无 TF 外部组在审构建；可测试 120"
    empty = ReviewSnapshot([], [], watch=WATCH_TESTFLIGHT)
    assert format_last_result(empty) == "当前无 TF 外部组在审构建；暂无可测试构建"
    missing_groups = ReviewSnapshot([], [], watch=WATCH_TESTFLIGHT, note="no_external_groups")
    assert format_last_result(missing_groups) == "没有 TestFlight 外部测试组"
    assert "没有 TestFlight 外部测试组" in build_success_message(
        "myapp", checked, missing_groups
    )
    missing_builds = ReviewSnapshot([], [], watch=WATCH_TESTFLIGHT, note="no_builds")
    assert format_last_result(missing_builds) == "外部测试组没有构建"
    assert "App Store" not in build_success_message("myapp", checked, snapshot)
    assert "在审版本" not in build_success_message("myapp", checked, snapshot)
    assert build_failure_message("myapp", checked, "凭证不完整", watch=WATCH_TESTFLIGHT) == (
        "应用：myapp\n"
        "监听：TestFlight 外部组版本审核\n"
        "检查时间：2026-10-14 09:31（Asia/Shanghai）\n"
        "检查失败：凭证不完整"
    )


def test_clamp_error_redacts_and_counts_code_points():
    text = "token=abc\nhttps://secret.example/path\n" + ("测" * 210)
    clamped = clamp_error(text)
    assert "token=[redacted]" in clamped
    assert "[redacted-url]" in clamped
    assert "\n" not in clamped
    assert len(clamped) == 200
