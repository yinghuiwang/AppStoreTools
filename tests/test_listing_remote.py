# tests/test_listing_remote.py
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from asc.listing.remote import NoEditableVersionError, load_asc_text_snapshot


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
