# tests/test_listing_remote.py
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from asc.listing.models import ListingSnapshot, LocaleListing
from asc.listing.remote import (
    NoEditableVersionError,
    attach_asc_screenshots,
    download_asc_screenshots,
    load_asc_text_snapshot,
    screenshot_thumb_url,
)


def test_load_asc_text_snapshot_merges_info_and_version_fields():
    api = MagicMock()
    api.get_editable_version.return_value = {
        "id": "v1",
        "attributes": {"versionString": "1.2.0", "appStoreState": "PREPARE_FOR_SUBMISSION"},
    }
    api.get_app_infos.return_value = [{"id": "ai1", "relationships": {}}]
    api.get_app_info_localizations.return_value = [
        {
            "id": "il1",
            "attributes": {
                "locale": "en-US",
                "name": "App",
                "subtitle": "Sub",
                "privacyPolicyUrl": "https://p",
            },
        },
    ]
    api.get_version_localizations.return_value = [
        {
            "id": "vl1",
            "attributes": {
                "locale": "en-US",
                "description": "D",
                "keywords": "k",
                "supportUrl": "https://s",
                "marketingUrl": "https://m",
            },
        },
    ]
    snap = load_asc_text_snapshot(api, "app1")
    assert snap.source == "asc"
    assert snap.version["versionString"] == "1.2.0"
    loc = snap.locales[0]
    assert loc.locale == "en-US"
    assert loc.fields["name"] == "App"
    assert loc.fields["description"] == "D"
    assert loc.fields["supportUrl"] == "https://s"
    assert loc.fields["subtitle"] == "Sub"
    assert loc.fields["privacyPolicyUrl"] == "https://p"
    assert loc.fields["keywords"] == "k"
    assert loc.fields["marketingUrl"] == "https://m"
    assert loc.screenshots == {}


def test_load_asc_text_snapshot_no_editable_version_raises():
    api = MagicMock()
    api.get_editable_version.return_value = None
    with pytest.raises(NoEditableVersionError):
        load_asc_text_snapshot(api, "app1")


def test_load_asc_text_snapshot_uses_select_app_info_id():
    api = MagicMock()
    api.get_editable_version.return_value = {
        "id": "v1",
        "attributes": {"versionString": "2.0", "appStoreState": "PREPARE_FOR_SUBMISSION"},
    }
    api.get_app_infos.return_value = [
        {"id": "ai-other", "relationships": {"appStoreVersions": {"data": {"id": "v99"}}}},
        {"id": "ai-match", "relationships": {"appStoreVersions": {"data": {"id": "v1"}}}},
    ]
    api.get_app_info_localizations.return_value = []
    api.get_version_localizations.return_value = []
    load_asc_text_snapshot(api, "app1")
    api.get_app_info_localizations.assert_called_once_with("ai-match")


def test_screenshot_thumb_url_replaces_template_size():
    url = screenshot_thumb_url(
        {"imageAsset": {"templateUrl": "https://example.com/{w}x{h}.png"}}
    )
    assert url == "https://example.com/100x100.png"


def test_attach_asc_screenshots_reads_sets():
    api = MagicMock()
    # version loc id en-US already on snapshot locales — attach looks up localization ids via get_version_localizations
    api.get_version_localizations.return_value = [
        {"id": "vl1", "attributes": {"locale": "en-US"}},
    ]
    api.get_screenshot_sets.return_value = {
        "data": [{
            "id": "set1",
            "attributes": {"screenshotDisplayType": "APP_IPHONE_67"},
            "relationships": {"appScreenshots": {"data": [{"id": "s1", "type": "appScreenshots"}]}},
        }],
        "included": [{
            "type": "appScreenshots",
            "id": "s1",
            "attributes": {
                "fileName": "shot.png",
                "imageAsset": {"templateUrl": "https://example.com/{w}x{h}.png"},
            },
        }],
    }
    base = ListingSnapshot(source="asc", locales=[LocaleListing("en-US", {}, {})], version={"id": "v1"})
    snap = attach_asc_screenshots(api, base)
    items = snap.locales[0].screenshots["APP_IPHONE_67"]
    assert items[0].remote_id == "s1"
    assert "100x100" in items[0].thumb_url


def test_download_asc_screenshots_overwrites_display_type(tmp_path):
    from PIL import Image

    locale_dir = tmp_path / "en-US"
    locale_dir.mkdir()
    old = locale_dir / "01_old.png"
    Image.new("RGB", (1290, 2796), color=(1, 2, 3)).save(old)
    other = locale_dir / "02_ipad.png"
    Image.new("RGB", (2048, 2732), color=(4, 5, 6)).save(other)

    api = MagicMock()
    api.get_editable_version.return_value = {
        "id": "v1",
        "attributes": {"versionString": "1.0", "appStoreState": "PREPARE_FOR_SUBMISSION"},
    }
    api.get_version_localizations.return_value = [
        {"id": "vl1", "attributes": {"locale": "en-US"}},
    ]
    api.get_screenshot_sets.return_value = {
        "data": [{
            "id": "set1",
            "attributes": {"screenshotDisplayType": "APP_IPHONE_67"},
            "relationships": {
                "appScreenshots": {
                    "data": [
                        {"id": "s1", "type": "appScreenshots"},
                        {"id": "s2", "type": "appScreenshots"},
                    ]
                }
            },
        }],
        "included": [
            {
                "type": "appScreenshots",
                "id": "s1",
                "attributes": {
                    "fileName": "a.png",
                    "imageAsset": {
                        "templateUrl": "https://cdn.example/{w}x{h}.{f}",
                        "width": 1290,
                        "height": 2796,
                    },
                },
            },
            {
                "type": "appScreenshots",
                "id": "s2",
                "attributes": {
                    "fileName": "b.png",
                    "imageAsset": {
                        "templateUrl": "https://cdn.example/{w}x{h}.{f}",
                        "width": 1290,
                        "height": 2796,
                    },
                },
            },
        ],
    }

    png_bytes = b""
    buf = tmp_path / "_src.png"
    Image.new("RGB", (10, 10), color=(9, 9, 9)).save(buf)
    png_bytes = buf.read_bytes()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = png_bytes
    mock_resp.raise_for_status = MagicMock()

    with patch("asc.listing.remote.requests.get", return_value=mock_resp) as get_mock:
        download_asc_screenshots(
            api,
            "app1",
            str(tmp_path),
            [{"locale": "en-US", "display_type": "APP_IPHONE_67"}],
        )

    assert not old.exists()
    assert other.exists()  # other displayType kept
    written = sorted(p.name for p in locale_dir.iterdir() if p.suffix == ".png" and p.name.startswith("0"))
    assert "01_a.png" in written or any(n.startswith("01_") for n in written)
    assert any(n.startswith("02_") for n in written if n != other.name)
    assert get_mock.call_count == 2
    # Full-res URL used for download
    assert "1290x2796" in get_mock.call_args_list[0].args[0]


def _mock_download_api_with_one_shot():
    api = MagicMock()
    api.get_editable_version.return_value = {
        "id": "v1",
        "attributes": {"versionString": "1.0", "appStoreState": "PREPARE_FOR_SUBMISSION"},
    }
    api.get_version_localizations.return_value = [
        {"id": "vl1", "attributes": {"locale": "en-US"}},
    ]
    api.get_screenshot_sets.return_value = {
        "data": [{
            "id": "set1",
            "attributes": {"screenshotDisplayType": "APP_IPHONE_67"},
            "relationships": {
                "appScreenshots": {"data": [{"id": "s1", "type": "appScreenshots"}]}
            },
        }],
        "included": [{
            "type": "appScreenshots",
            "id": "s1",
            "attributes": {
                "fileName": "home.png",
                "imageAsset": {
                    "templateUrl": "https://cdn.example/{w}x{h}.{f}",
                    "width": 1290,
                    "height": 2796,
                },
            },
        }],
    }
    return api


def test_download_asc_screenshots_writes_into_mapped_en_folder(tmp_path):
    """`en/` maps to en-US via SCREENSHOT_FOLDER_TO_LOCALE — pull must overwrite en/, not create en-US/."""
    from PIL import Image

    en_dir = tmp_path / "en"
    en_dir.mkdir()
    old = en_dir / "01_old.png"
    Image.new("RGB", (1290, 2796), color=(1, 2, 3)).save(old)

    api = _mock_download_api_with_one_shot()
    buf = tmp_path / "_src.png"
    Image.new("RGB", (10, 10), color=(9, 9, 9)).save(buf)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = buf.read_bytes()
    mock_resp.raise_for_status = MagicMock()

    with patch("asc.listing.remote.requests.get", return_value=mock_resp):
        download_asc_screenshots(
            api,
            "app1",
            str(tmp_path),
            [{"locale": "en-US", "display_type": "APP_IPHONE_67"}],
        )

    assert not (tmp_path / "en-US").exists()  # must not create sibling ASC-named folder
    assert en_dir.is_dir()
    assert not old.exists()
    written = list(en_dir.glob("*.png"))
    assert len(written) == 1
    assert written[0].name.startswith("01_")
