"""CLI tests for asc iap-screenshots."""
from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from asc.cli import app
from asc.guard import GuardViolationError
from asc.commands.iap_review_screenshots import (
    ReviewScreenshotScanResult,
    ReviewScreenshotTarget,
)


runner = CliRunner()


def test_iap_screenshots_command_registered():
    result = runner.invoke(app, ["iap-screenshots", "--help"])

    assert result.exit_code == 0
    assert "review" in result.output.lower() or "审核截图" in result.output


def test_iap_screenshots_no_prompt_uploads_default_paths(tmp_path):
    shot = tmp_path / "coins.png"
    shot.write_bytes(b"png")
    scan = ReviewScreenshotScanResult(
        targets=[
            ReviewScreenshotTarget(
                kind="iap",
                id="iap_1",
                product_id="coins.100",
                name="100 Coins",
                default_path=str(shot),
            ),
            ReviewScreenshotTarget(
                kind="subscription",
                id="sub_1",
                product_id="premium.monthly",
                name="Premium Monthly",
            ),
        ]
    )

    with (
        patch("asc.commands.iap_review_screenshots.Config"),
        patch(
            "asc.commands.iap_review_screenshots.resolve_app_profile",
            return_value="testapp",
        ),
        patch(
            "asc.commands.iap_review_screenshots.make_api_from_config",
            return_value=(object(), "app_1"),
        ),
        patch("asc.commands.iap_review_screenshots.Guard") as guard_cls,
        patch(
            "asc.commands.iap_review_screenshots.scan_missing_review_screenshots",
            return_value=scan,
        ),
        patch(
            "asc.commands.iap_review_screenshots.extract_review_screenshot_paths",
            return_value={},
        ),
        patch("asc.commands.iap_review_screenshots.upload_review_screenshots") as upload,
    ):
        guard_cls.return_value.is_enabled.return_value = False
        upload.return_value.failed = 0
        result = runner.invoke(app, ["iap-screenshots", "--no-prompt", "--yes"])

    assert result.exit_code == 0
    upload.assert_called_once()
    uploaded_items = upload.call_args.args[1]
    assert len(uploaded_items) == 1
    assert uploaded_items[0].product_id == "coins.100"


def test_iap_screenshots_no_prompt_exits_zero_when_nothing_selected():
    scan = ReviewScreenshotScanResult(
        targets=[
            ReviewScreenshotTarget(
                kind="iap", id="iap_1", product_id="coins.100", name="100 Coins"
            ),
        ]
    )

    with (
        patch("asc.commands.iap_review_screenshots.Config"),
        patch(
            "asc.commands.iap_review_screenshots.resolve_app_profile",
            return_value="testapp",
        ),
        patch(
            "asc.commands.iap_review_screenshots.make_api_from_config",
            return_value=(object(), "app_1"),
        ),
        patch("asc.commands.iap_review_screenshots.Guard") as guard_cls,
        patch(
            "asc.commands.iap_review_screenshots.scan_missing_review_screenshots",
            return_value=scan,
        ),
        patch(
            "asc.commands.iap_review_screenshots.extract_review_screenshot_paths",
            return_value={},
        ),
        patch("asc.commands.iap_review_screenshots.upload_review_screenshots") as upload,
    ):
        guard_cls.return_value.is_enabled.return_value = False
        result = runner.invoke(app, ["iap-screenshots", "--no-prompt", "--yes"])

    assert result.exit_code == 0
    assert "没有选择" in result.output or "No screenshots selected" in result.output
    upload.assert_not_called()


def test_iap_screenshots_accepts_app_option_and_uses_profile_resolution():
    scan = ReviewScreenshotScanResult(targets=[])

    with (
        patch("asc.commands.iap_review_screenshots.Config") as config_cls,
        patch(
            "asc.commands.iap_review_screenshots.resolve_app_profile",
            return_value="testapp",
        ) as resolve,
        patch(
            "asc.commands.iap_review_screenshots.make_api_from_config",
            return_value=(object(), "app_1"),
        ),
        patch("asc.commands.iap_review_screenshots.Guard") as guard_cls,
        patch(
            "asc.commands.iap_review_screenshots.scan_missing_review_screenshots",
            return_value=scan,
        ),
        patch(
            "asc.commands.iap_review_screenshots.extract_review_screenshot_paths",
            return_value={},
        ),
        patch("asc.commands.iap_review_screenshots.upload_review_screenshots") as upload,
    ):
        guard_cls.return_value.is_enabled.return_value = False
        result = runner.invoke(
            app, ["iap-screenshots", "--app", "testapp", "--no-prompt", "--yes"]
        )

    assert result.exit_code == 0
    assert config_cls.call_args_list[0].args == ("testapp",)
    resolve.assert_called_once_with("testapp", config_cls.return_value)
    upload.assert_not_called()


def test_iap_screenshots_guard_violation_blocks_before_upload():
    guard_error = GuardViolationError("blocked by guard")

    with (
        patch("asc.commands.iap_review_screenshots.Config"),
        patch(
            "asc.commands.iap_review_screenshots.resolve_app_profile",
            return_value="testapp",
        ),
        patch("asc.commands.iap_review_screenshots.Guard") as guard_cls,
        patch(
            "asc.commands.iap_review_screenshots.make_api_from_config",
            return_value=(object(), "app_1"),
        ) as make_api,
        patch(
            "asc.commands.iap_review_screenshots.scan_missing_review_screenshots"
        ) as scan,
        patch("asc.commands.iap_review_screenshots.upload_review_screenshots") as upload,
    ):
        guard = guard_cls.return_value
        guard.is_enabled.return_value = True
        guard.check_and_enforce.side_effect = guard_error

        result = runner.invoke(app, ["iap-screenshots", "--no-prompt", "--yes"])

    assert result.exit_code != 0
    assert "blocked by guard" in result.output
    make_api.assert_not_called()
    scan.assert_not_called()
    upload.assert_not_called()
