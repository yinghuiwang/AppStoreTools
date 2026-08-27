# tests/test_web_listing.py
"""Unit tests for metadata upload locale/field filtering via /api/metadata/run."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from asc.web.server import create_app
from asc.web.tasks import TaskStatus


@pytest.fixture(autouse=True)
def isolated_web_task_guard(monkeypatch):
    monkeypatch.setattr(
        "asc.web.routes_api.enforce_config_guard",
        MagicMock(),
    )
    monkeypatch.setattr(
        "asc.web.routes_listing.enforce_config_guard",
        MagicMock(),
    )


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def _wait_for_task(routes_api, task_id, timeout_iters=100):
    task = None
    for _ in range(timeout_iters):
        task = routes_api._task_store.get(task_id)
        if task and task["status"] in {TaskStatus.DONE, TaskStatus.ERROR, TaskStatus.CANCELED}:
            break
        time.sleep(0.02)
    return task


def test_metadata_run_filters_by_locale_and_fields(client, tmp_path):
    """POST /api/metadata/run with locales_json/fields_by_locale_json filters rows before upload."""
    from asc.web import routes_api

    csv_path = tmp_path / "appstore_info.csv"
    csv_path.write_text(
        "locale,name,keywords,description\n"
        "en-US,A,k,d\n"
        "zh-Hans,中,词,描述\n",
        encoding="utf-8",
    )

    mock_config = MagicMock()
    mock_api = MagicMock()

    captured = {}

    def fake_upload_metadata_core(api, app_id, metadata_list, **kwargs):
        captured["metadata_list"] = metadata_list
        return {"success": True}

    with patch("asc.web.routes_api.Config", return_value=mock_config), \
         patch("asc.web.routes_api.make_api_from_config", return_value=(mock_api, "app123")), \
         patch("asc.commands.metadata._upload_metadata_core", side_effect=fake_upload_metadata_core):
        response = client.post(
            "/api/metadata/run",
            cookies={"asc_profile": "test"},
            data={
                "csv_path": str(csv_path),
                "include_metadata": "1",
                "include_screenshots": "",
                "dry_run": "1",
                "locales_json": json.dumps(["en-US"]),
                "fields_by_locale_json": json.dumps({"en-US": ["name", "keywords"]}),
            },
        )
        assert response.status_code == 200
        task_id = response.json()["task_id"]
        task = _wait_for_task(routes_api, task_id)

    assert task is not None
    assert task["status"] == TaskStatus.DONE
    assert captured["metadata_list"] == [{"locale": "en-US", "name": "A", "keywords": "k"}]


def test_metadata_run_empty_filters_uploads_all_rows(client, tmp_path):
    """Empty locales_json/fields_by_locale_json means no filtering (all rows uploaded as-is)."""
    from asc.web import routes_api

    csv_path = tmp_path / "appstore_info.csv"
    csv_path.write_text(
        "locale,name,keywords\n"
        "en-US,A,k\n"
        "zh-Hans,中,词\n",
        encoding="utf-8",
    )

    mock_config = MagicMock()
    mock_api = MagicMock()

    captured = {}

    def fake_upload_metadata_core(api, app_id, metadata_list, **kwargs):
        captured["metadata_list"] = metadata_list
        return {"success": True}

    with patch("asc.web.routes_api.Config", return_value=mock_config), \
         patch("asc.web.routes_api.make_api_from_config", return_value=(mock_api, "app123")), \
         patch("asc.commands.metadata._upload_metadata_core", side_effect=fake_upload_metadata_core):
        response = client.post(
            "/api/metadata/run",
            cookies={"asc_profile": "test"},
            data={
                "csv_path": str(csv_path),
                "include_metadata": "1",
                "include_screenshots": "",
                "dry_run": "1",
                "locales_json": "",
                "fields_by_locale_json": "",
            },
        )
        assert response.status_code == 200
        task_id = response.json()["task_id"]
        task = _wait_for_task(routes_api, task_id)

    assert task is not None
    assert task["status"] == TaskStatus.DONE
    assert captured["metadata_list"] == [
        {"locale": "en-US", "name": "A", "keywords": "k"},
        {"locale": "zh-Hans", "name": "中", "keywords": "词"},
    ]


def test_metadata_run_filter_yields_empty_returns_400(client, tmp_path):
    """When include_metadata is set, screenshots are not included, and filtering yields
    zero rows, the endpoint returns HTTP 400 before starting a task."""
    csv_path = tmp_path / "appstore_info.csv"
    csv_path.write_text(
        "locale,name\n"
        "en-US,A\n",
        encoding="utf-8",
    )

    mock_config = MagicMock()

    with patch("asc.web.routes_api.Config", return_value=mock_config):
        response = client.post(
            "/api/metadata/run",
            cookies={"asc_profile": "test"},
            data={
                "csv_path": str(csv_path),
                "include_metadata": "1",
                "include_screenshots": "",
                "dry_run": "1",
                "locales_json": json.dumps(["ja"]),
                "fields_by_locale_json": "",
            },
        )

    assert response.status_code == 400
    data = response.json()
    assert "error" in data


def test_metadata_run_invalid_locales_json_returns_400(client):
    """Malformed locales_json returns 400."""
    response = client.post(
        "/api/metadata/run",
        cookies={"asc_profile": "test"},
        data={
            "include_metadata": "1",
            "locales_json": "not valid json {",
        },
    )
    assert response.status_code == 400
    data = response.json()
    assert "error" in data


def test_metadata_run_invalid_fields_by_locale_json_returns_400(client):
    """Malformed fields_by_locale_json returns 400."""
    response = client.post(
        "/api/metadata/run",
        cookies={"asc_profile": "test"},
        data={
            "include_metadata": "1",
            "fields_by_locale_json": "not valid json {",
        },
    )
    assert response.status_code == 400
    data = response.json()
    assert "error" in data


def test_metadata_run_explicit_empty_locales_json_returns_400(client):
    """Workbench-style locales_json=`[]` must not mean upload-all when metadata is included."""
    response = client.post(
        "/api/metadata/run",
        cookies={"asc_profile": "test"},
        data={
            "include_metadata": "1",
            "include_screenshots": "",
            "dry_run": "1",
            "locales_json": "[]",
            "fields_by_locale_json": "",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "no metadata rows selected"


def test_metadata_run_explicit_empty_fields_by_locale_returns_400(client):
    """Workbench-style fields_by_locale_json=`{}` is explicit empty → 400."""
    response = client.post(
        "/api/metadata/run",
        cookies={"asc_profile": "test"},
        data={
            "include_metadata": "1",
            "include_screenshots": "",
            "dry_run": "1",
            "locales_json": "",
            "fields_by_locale_json": "{}",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "no metadata rows selected"


def test_metadata_run_explicit_empty_screenshot_scopes_object_returns_400(client):
    """Workbench-style screenshot_scopes_json=`{}` is explicit empty → 400."""
    response = client.post(
        "/api/metadata/run",
        cookies={"asc_profile": "test"},
        data={
            "include_metadata": "",
            "include_screenshots": "1",
            "dry_run": "1",
            "screenshot_scopes_json": "{}",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "no screenshots selected"


def test_metadata_run_explicit_empty_screenshot_scopes_list_returns_400(client):
    """Explicit screenshot_scopes_json=`[]` is empty selection → 400."""
    response = client.post(
        "/api/metadata/run",
        cookies={"asc_profile": "test"},
        data={
            "include_metadata": "",
            "include_screenshots": "1",
            "dry_run": "1",
            "screenshot_scopes_json": "[]",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "no screenshots selected"


def test_metadata_run_locales_json_is_passed_to_screenshot_core(client, tmp_path):
    """Upload-tab locale list (no screenshot_scopes) still limits screenshot jobs."""
    from asc.web import routes_api

    shots = tmp_path / "screenshots"
    shots.mkdir()
    captured = {}

    def fake_upload_screenshots_core(*args, **kwargs):
        captured["kwargs"] = kwargs
        return None

    with patch("asc.web.routes_api.Config", return_value=MagicMock()), \
         patch("asc.web.routes_api.make_api_from_config", return_value=(MagicMock(), "app123")), \
         patch(
             "asc.commands.screenshots._upload_screenshots_core",
             side_effect=fake_upload_screenshots_core,
         ):
        response = client.post(
            "/api/metadata/run",
            cookies={"asc_profile": "test"},
            data={
                "screenshots_dir": str(shots),
                "include_metadata": "",
                "include_screenshots": "1",
                "dry_run": "1",
                "locales_json": json.dumps(["zh-Hans"]),
            },
        )
        assert response.status_code == 200
        task_id = response.json()["task_id"]
        task = _wait_for_task(routes_api, task_id)

    assert task is not None
    assert task["status"] == TaskStatus.DONE
    assert captured["kwargs"]["locales"] == ["zh-Hans"]
    assert captured["kwargs"]["screenshot_scopes"] is None


def test_metadata_run_omitted_filter_fields_legacy_unfiltered_200(client, tmp_path):
    """Omitted filter fields (not present in form) keep legacy unfiltered upload."""
    from asc.web import routes_api

    csv_path = tmp_path / "appstore_info.csv"
    csv_path.write_text(
        "locale,name\nen-US,A\nzh-Hans,中\n",
        encoding="utf-8",
    )

    mock_config = MagicMock()
    mock_api = MagicMock()
    captured = {}

    def fake_upload_metadata_core(api, app_id, metadata_list, **kwargs):
        captured["metadata_list"] = metadata_list
        return {"success": True}

    with patch("asc.web.routes_api.Config", return_value=mock_config), \
         patch("asc.web.routes_api.make_api_from_config", return_value=(mock_api, "app123")), \
         patch("asc.commands.metadata._upload_metadata_core", side_effect=fake_upload_metadata_core):
        response = client.post(
            "/api/metadata/run",
            cookies={"asc_profile": "test"},
            data={
                "csv_path": str(csv_path),
                "include_metadata": "1",
                "include_screenshots": "",
                "dry_run": "1",
                # locales_json / fields_by_locale_json intentionally omitted
            },
        )
        assert response.status_code == 200
        task_id = response.json()["task_id"]
        task = _wait_for_task(routes_api, task_id)

    assert task is not None
    assert task["status"] == TaskStatus.DONE
    assert len(captured["metadata_list"]) == 2


# ---------- /api/listing/local (local text workbench) ----------


def test_listing_local_requires_profile(client, tmp_path):
    """GET without an asc_profile cookie returns the standard no-profile payload."""
    p = tmp_path / "app.csv"
    p.write_text("locale,name\nen-US,Old\n", encoding="utf-8-sig")
    r = client.get("/api/listing/local", params={"csv_path": str(p)})
    assert r.status_code == 400
    assert r.json()["ok"] is False


def test_listing_local_and_save(client, tmp_path):
    p = tmp_path / "app.csv"
    p.write_text("locale,name\nen-US,Old\n", encoding="utf-8-sig")

    r = client.get(
        "/api/listing/local",
        params={"csv_path": str(p)},
        cookies={"asc_profile": "test"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    by_locale = {loc["locale"]: loc for loc in data["snapshot"]["locales"]}
    assert by_locale["en-US"]["fields"]["name"] == "Old"
    assert by_locale["en-US"]["screenshots"] == {}
    mtime = data["mtime"]

    body = {
        "csv_path": str(p),
        "expected_mtime": mtime,
        "locales": [{"locale": "en-US", "fields": {"name": "New"}}],
    }
    r2 = client.post(
        "/api/listing/local/save",
        json=body,
        cookies={"asc_profile": "test"},
    )
    assert r2.status_code == 200
    assert r2.json()["ok"] is True
    assert "New" in p.read_text(encoding="utf-8-sig")


def test_listing_local_save_conflict_returns_409(client, tmp_path):
    """A stale expected_mtime (file changed on disk since loading) returns 409."""
    import time

    p = tmp_path / "app.csv"
    p.write_text("locale,name\nen-US,A\n", encoding="utf-8-sig")
    stale_mtime = p.stat().st_mtime
    time.sleep(0.02)
    p.write_text("locale,name\nen-US,B\n", encoding="utf-8-sig")

    body = {
        "csv_path": str(p),
        "expected_mtime": stale_mtime,
        "locales": [{"locale": "en-US", "fields": {"name": "C"}}],
    }
    r = client.post(
        "/api/listing/local/save",
        json=body,
        cookies={"asc_profile": "test"},
    )
    assert r.status_code == 409


def test_listing_local_save_requires_profile(client, tmp_path):
    p = tmp_path / "app.csv"
    p.write_text("locale,name\nen-US,Old\n", encoding="utf-8-sig")
    body = {
        "csv_path": str(p),
        "expected_mtime": None,
        "locales": [{"locale": "en-US", "fields": {"name": "New"}}],
    }
    r = client.post("/api/listing/local/save", json=body)
    assert r.status_code == 400
    assert r.json()["ok"] is False


def test_listing_local_missing_csv_returns_empty_snapshot(client, tmp_path):
    missing = tmp_path / "does-not-exist.csv"
    r = client.get(
        "/api/listing/local",
        params={"csv_path": str(missing)},
        cookies={"asc_profile": "test"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["exists"] is False
    assert data["hasContent"] is False
    assert data["snapshot"]["locales"] == []


# ---------- /api/listing/local screenshots merge + thumb + edit endpoints ----------


def _make_png(path, size=(1290, 2796)):
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color=(10, 20, 30)).save(path)


def test_listing_local_merges_screenshots_when_dir_given(client, tmp_path):
    p = tmp_path / "app.csv"
    p.write_text("locale,name\nen-US,Old\n", encoding="utf-8-sig")
    shots = tmp_path / "screenshots"
    _make_png(shots / "en-US" / "01_a.png")

    r = client.get(
        "/api/listing/local",
        params={"csv_path": str(p), "screenshots_dir": str(shots)},
        cookies={"asc_profile": "test"},
    )
    assert r.status_code == 200
    data = r.json()
    by_locale = {loc["locale"]: loc for loc in data["snapshot"]["locales"]}
    screenshots = by_locale["en-US"]["screenshots"]
    assert "APP_IPHONE_67" in screenshots
    items = screenshots["APP_IPHONE_67"]
    assert items[0]["file_name"] == "01_a.png"
    assert items[0]["thumb_url"].startswith("/api/listing/thumb?path=")


def test_listing_local_without_screenshots_dir_leaves_empty(client, tmp_path):
    p = tmp_path / "app.csv"
    p.write_text("locale,name\nen-US,Old\n", encoding="utf-8-sig")
    r = client.get(
        "/api/listing/local",
        params={"csv_path": str(p)},
        cookies={"asc_profile": "test"},
    )
    assert r.status_code == 200
    by_locale = {loc["locale"]: loc for loc in r.json()["snapshot"]["locales"]}
    assert by_locale["en-US"]["screenshots"] == {}


def test_listing_thumb_serves_file_under_root(client, tmp_path):
    shots = tmp_path / "screenshots"
    img_path = shots / "en-US" / "01_a.png"
    _make_png(img_path)

    r = client.get(
        "/api/listing/thumb",
        params={"path": str(img_path), "root": str(shots)},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/")
    assert len(r.content) > 0


def test_listing_thumb_rejects_path_outside_root(client, tmp_path):
    shots = tmp_path / "screenshots"
    outside = tmp_path / "outside"
    img_path = outside / "secret.png"
    _make_png(img_path)

    r = client.get(
        "/api/listing/thumb",
        params={"path": str(img_path), "root": str(shots)},
    )
    assert r.status_code == 400


def test_listing_thumb_missing_file_returns_404(client, tmp_path):
    shots = tmp_path / "screenshots"
    shots.mkdir()
    r = client.get(
        "/api/listing/thumb",
        params={"path": str(shots / "nope.png"), "root": str(shots)},
    )
    assert r.status_code == 404


def test_listing_screenshots_reorder(client, tmp_path):
    shots = tmp_path / "screenshots"
    _make_png(shots / "en-US" / "01_a.png")
    _make_png(shots / "en-US" / "02_b.png")

    r = client.post(
        "/api/listing/screenshots/reorder",
        json={
            "root": str(shots),
            "locale": "en-US",
            "display_type": "APP_IPHONE_67",
            "file_names": ["02_b.png", "01_a.png"],
        },
        cookies={"asc_profile": "test"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    names = sorted(f.name for f in (shots / "en-US").iterdir())
    assert names == ["01_b.png", "02_a.png"]
    assert "groups" in data
    assert [i["file_name"] for i in data["groups"]["APP_IPHONE_67"]] == ["01_b.png", "02_a.png"]
    assert [i["file_name"] for i in data["items"]] == ["01_b.png", "02_a.png"]


def test_listing_screenshots_reorder_returns_sibling_display_types(client, tmp_path):
    """N1: renumbering the folder must refresh sibling displayType filenames in the response."""
    from urllib.parse import unquote

    shots = tmp_path / "screenshots"
    # Gap in numbering so sibling is renumbered (05 → 03), not only the reordered type.
    _make_png(shots / "en-US" / "01_iphone_a.png", size=(1290, 2796))
    _make_png(shots / "en-US" / "03_iphone_b.png", size=(1290, 2796))
    _make_png(shots / "en-US" / "05_ipad.png", size=(2048, 2732))

    r = client.post(
        "/api/listing/screenshots/reorder",
        json={
            "root": str(shots),
            "locale": "en-US",
            "display_type": "APP_IPHONE_67",
            "file_names": ["03_iphone_b.png", "01_iphone_a.png"],
        },
        cookies={"asc_profile": "test"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    groups = data["groups"]
    assert set(groups.keys()) == {"APP_IPHONE_67", "APP_IPAD_PRO_3GEN_129"}
    assert [i["file_name"] for i in groups["APP_IPHONE_67"]] == [
        "01_iphone_b.png",
        "02_iphone_a.png",
    ]
    ipad = groups["APP_IPAD_PRO_3GEN_129"]
    assert [i["file_name"] for i in ipad] == ["03_ipad.png"]
    assert ipad[0]["local_path"].endswith("03_ipad.png")
    assert "03_ipad.png" in unquote(ipad[0]["thumb_url"])


def test_listing_screenshots_reorder_requires_profile(client, tmp_path):
    shots = tmp_path / "screenshots"
    _make_png(shots / "en-US" / "01_a.png")
    r = client.post(
        "/api/listing/screenshots/reorder",
        json={
            "root": str(shots),
            "locale": "en-US",
            "display_type": "APP_IPHONE_67",
            "file_names": ["01_a.png"],
        },
    )
    assert r.status_code == 400
    assert r.json()["ok"] is False


def test_listing_screenshots_reorder_missing_locale_returns_404(client, tmp_path):
    shots = tmp_path / "screenshots"
    shots.mkdir()
    r = client.post(
        "/api/listing/screenshots/reorder",
        json={
            "root": str(shots),
            "locale": "ja",
            "display_type": "APP_IPHONE_67",
            "file_names": ["01_a.png"],
        },
        cookies={"asc_profile": "test"},
    )
    assert r.status_code == 404


def test_listing_screenshots_replace(client, tmp_path):
    shots = tmp_path / "screenshots"
    img_path = shots / "en-US" / "01_a.png"
    _make_png(img_path)

    r = client.post(
        "/api/listing/screenshots/replace",
        data={"root": str(shots), "path": str(img_path)},
        files={"file": ("new.png", b"new-image-bytes", "image/png")},
        cookies={"asc_profile": "test"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert img_path.read_bytes() == b"new-image-bytes"


def test_listing_screenshots_replace_rejects_path_outside_root(client, tmp_path):
    shots = tmp_path / "screenshots"
    shots.mkdir()
    outside = tmp_path / "outside" / "x.png"
    _make_png(outside)

    r = client.post(
        "/api/listing/screenshots/replace",
        data={"root": str(shots), "path": str(outside)},
        files={"file": ("new.png", b"new-image-bytes", "image/png")},
        cookies={"asc_profile": "test"},
    )
    assert r.status_code == 400


def test_listing_screenshots_delete(client, tmp_path):
    shots = tmp_path / "screenshots"
    img_path = shots / "en-US" / "01_a.png"
    _make_png(img_path)

    r = client.post(
        "/api/listing/screenshots/delete",
        json={"root": str(shots), "path": str(img_path)},
        cookies={"asc_profile": "test"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert not img_path.exists()


def test_listing_screenshots_delete_rejects_path_outside_root(client, tmp_path):
    shots = tmp_path / "screenshots"
    shots.mkdir()
    outside = tmp_path / "outside" / "x.png"
    _make_png(outside)

    r = client.post(
        "/api/listing/screenshots/delete",
        json={"root": str(shots), "path": str(outside)},
        cookies={"asc_profile": "test"},
    )
    assert r.status_code == 400
    assert outside.exists()


def test_listing_screenshots_add(client, tmp_path):
    shots = tmp_path / "screenshots"
    shots.mkdir()

    r = client.post(
        "/api/listing/screenshots/add",
        data={"root": str(shots), "locale": "en-US", "display_type": "APP_IPHONE_67"},
        files={"file": ("03_new.png", b"png-bytes", "image/png")},
        cookies={"asc_profile": "test"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert (shots / "en-US" / "03_new.png").read_bytes() == b"png-bytes"


def test_listing_screenshots_add_rejects_locale_traversal(client, tmp_path):
    shots = tmp_path / "screenshots"
    shots.mkdir()

    r = client.post(
        "/api/listing/screenshots/add",
        data={
            "root": str(shots),
            "locale": "../outside",
            "display_type": "APP_IPHONE_67",
            "filename": "x.png",
        },
        files={"file": ("x.png", b"png-bytes", "image/png")},
        cookies={"asc_profile": "test"},
    )
    assert r.status_code == 400
    assert not (tmp_path / "outside").exists()
    assert not (tmp_path / "outside" / "x.png").exists()


def test_listing_screenshots_add_rejects_filename_traversal(client, tmp_path):
    shots = tmp_path / "screenshots"
    shots.mkdir()
    (shots / "en-US").mkdir()

    r = client.post(
        "/api/listing/screenshots/add",
        data={
            "root": str(shots),
            "locale": "en-US",
            "display_type": "APP_IPHONE_67",
            "filename": "../escape.png",
        },
        files={"file": ("escape.png", b"png-bytes", "image/png")},
        cookies={"asc_profile": "test"},
    )
    assert r.status_code == 400
    assert not (shots / "escape.png").exists()


def test_listing_screenshots_replace_rejects_new_name_traversal(client, tmp_path):
    shots = tmp_path / "screenshots"
    img_path = shots / "en-US" / "01_a.png"
    _make_png(img_path)

    r = client.post(
        "/api/listing/screenshots/replace",
        data={
            "root": str(shots),
            "path": str(img_path),
            "new_name": "../evil.png",
        },
        files={"file": ("new.png", b"new-image-bytes", "image/png")},
        cookies={"asc_profile": "test"},
    )
    assert r.status_code == 400
    assert img_path.read_bytes() != b"new-image-bytes"
    assert not (shots / "evil.png").exists()


def test_upload_step_forwards_workbench_scope():
    """Upload step reuses useListingScope checkboxes and the metadata run payload."""
    src = Path("frontend/src/views/listing/UploadStep.vue").read_text(encoding="utf-8")
    assert "useListingScope" in src
    assert "locales_json" in src
    assert "fields_by_locale_json" in src
    assert "screenshot_scopes_json" in src
    assert "metadata.wb_empty_selection" in src
    assert "selectedLocales" not in src
    assert "toggleLocale" not in src
    assert "toggleAll" not in src
    assert "APP_IPHONE" not in src
    assert "includeMetadata" in src
    assert "includeScreenshots" in src
    assert "metadata.scope" in src
    assert 'class="field-row scope-row"' in src
    assert "review-screenshots" not in src
    assert "accordion" not in src.lower()


def test_listing_scope_composable_matches_old_payloads():
    src = Path("frontend/src/composables/useListingScope.ts").read_text(encoding="utf-8")
    assert "localesJson" in src
    assert "fieldsByLocaleJson" in src
    assert "screenshotScopesJson" in src
    assert "selectDiffsOnly" in src
    assert "local_only" in src
    assert "hasMetadataSelection" in src
    assert "hasScreenshotSelection" in src


def test_listing_wizard_views_exist():
    root = Path("frontend/src")
    src = (root / "views/ListingView.vue").read_text(encoding="utf-8")
    assert "listing-wizard" in src
    assert "<t-steps" in src
    assert "t-step-item" in src
    assert 'v-model:current="current"' in src
    assert "listing.step.create" in src
    assert "listing.step.preview" in src
    assert "listing.step.upload" in src
    assert "CreateStep" in src
    assert "PreviewStep" in src
    assert "UploadStep" in src
    assert "useListingWorkflow" in src
    assert "appliedTick" in src
    assert 'tab === "local"' in src
    assert 'tab === "diff" || tab === "upload"' in src
    assert 'hasContent.value ? "preview"' not in src
    assert "didDefault" not in src
    assert 'step.value = "preview"' not in src
    mounted = re.search(r"onMounted\(async \(\) => \{.*?\}\);", src, re.S)
    assert mounted, "ListingView onMounted missing"
    assert "hasContent" not in mounted.group(0)
    applied = re.search(r"watch\(appliedTick, \(\) => \{.*?\}\);", src, re.S)
    assert applied, "ListingView appliedTick watcher missing"
    assert "workflow.reloadFromDisk()" in applied.group(0)
    workflow_src = (root / "composables/useListingWorkflow.ts").read_text(encoding="utf-8")
    assert "reloadFromDisk:" in workflow_src
    assert "dropDraft()" in workflow_src
    assert "hasContent" not in applied.group(0)
    assert "preview" not in applied.group(0)
    assert "LocalTab" not in src
    assert "DiffTab" not in src
    assert "UploadTab" not in src
    phase = (root / "composables/useTaskPagePhase.ts").read_text(encoding="utf-8")
    assert 'DEFAULT_LISTING_STEP = "create"' in phase
    assert '"create"' in phase and '"preview"' in phase and '"upload"' in phase
    create = (root / "views/listing/CreateStep.vue").read_text(encoding="utf-8")
    tab_values = [
        m.group(1)
        for m in re.finditer(r'<t-tab-panel[^>]*\bvalue="([^"]+)"', create)
    ]
    assert tab_values == ["csv", "asc", "blank", "agent"]
    assert "write: false" in create
    assert "infer" not in create.lower()
    assert 'destroy-on-hide="false"' in create
    assert "ExampleHelp" in create
    assert 'kind="csv"' in create
    assert 'kind="shots"' in create
    assert "listing.csv_path_help" in create
    assert "metadata.csv_path" in create
    assert "metadata.shots_dir" in create
    assert 'emit("next")' not in create
    assert "listing.skip_to_preview" in create
    assert "listing.file_opened" in create
    assert "listing.draft_applied" in create
    preview = (root / "views/listing/PreviewStep.vue").read_text(encoding="utf-8")
    upload = (root / "views/listing/UploadStep.vue").read_text(encoding="utf-8")
    assert "ExampleHelp" not in preview
    assert "ExampleHelp" not in upload
    assert "filebrowser.browse" not in preview
    assert "filebrowser.browse" not in upload
    assert "setCsvPath" not in preview
    assert "setCsvPath" not in upload
    assert "setScreenshotsDir" not in upload
    assert "openExistingCsv" not in preview
    assert "workflow.csvPath.value" in upload
    assert "workflow.screenshotsDir.value" in upload
    assert ':disabled="workflow.emptyProfile.value" @click="startUpload"' not in src
    assert '@click="startUpload"' in src
    assert "MessagePlugin" in src
    assert "nav.select_app" in src
    assert "MessagePlugin" in upload
    assert "metadata.need_scope" in upload
    assert "metadata.wb_empty_selection" in upload


def test_listing_preview_has_screenshot_workbench():
    src = Path("frontend/src/views/listing/PreviewStep.vue").read_text(encoding="utf-8")
    dialog = Path("frontend/src/views/listing/ListingEditorDialog.vue").read_text(encoding="utf-8")
    assert "/api/listing/screenshots/add" in src
    assert "/api/listing/screenshots/replace" in src
    assert "/api/listing/screenshots/delete" in src
    assert "/api/listing/screenshots/reorder" in src
    assert "ListingEditorDialog" in src
    assert "LocalePicker" in src
    assert "file-hidden" in src
    assert "openAddShot" in src
    assert "openReplaceShot" in src
    assert src.count('type="file"') == 1
    assert "未选择任何文件" not in src
    assert "<template #icon>" in src
    assert 'shape="square"' in src
    assert "openAddShot(entry.row.locale, '')" in src
    assert "useListingScope" not in src
    assert "ensureCompare" in src
    assert "onMounted(() => { void workflow.ensureCompare" not in src
    assert "/api/listing/screenshots/" not in dialog
    assert "status=\"warning\"" in dialog or ':status="statusFor' in dialog
    assert "width=\"820px\"" in dialog
    assert "listing.agent_seed_edit" in dialog


def test_listing_preview_shows_full_description():
    src = Path("frontend/src/views/listing/PreviewStep.vue").read_text(encoding="utf-8")
    assert "listing.col_description" in src
    assert "listing.desc_empty" in src
    assert "descriptionText" in src
    assert "fields.description" in src
    assert "white-space: pre-wrap" in src
    assert "desc-body" in src
    assert "clip(entry.row.fields.description" not in src
    assert "metadata.shots_section" in src


def test_listing_screenshots_add_requires_profile(client, tmp_path):
    shots = tmp_path / "screenshots"
    shots.mkdir()
    r = client.post(
        "/api/listing/screenshots/add",
        data={"root": str(shots), "locale": "en-US", "display_type": "APP_IPHONE_67"},
        files={"file": ("03_new.png", b"png-bytes", "image/png")},
    )
    assert r.status_code == 400
    assert r.json()["ok"] is False


# ---------- /api/listing/diff + /api/listing/pull/text ----------


def _mock_asc_api_for_text():
    mock_api = MagicMock()
    mock_api.get_editable_version.return_value = {
        "id": "v1",
        "attributes": {"versionString": "1.2.0", "appStoreState": "PREPARE_FOR_SUBMISSION"},
    }
    mock_api.get_app_infos.return_value = [{"id": "ai1", "relationships": {}}]
    mock_api.get_app_info_localizations.return_value = [
        {
            "id": "il1",
            "attributes": {
                "locale": "en-US",
                "name": "ASC Name",
                "subtitle": "ASC Sub",
                "privacyPolicyUrl": "https://p.asc",
            },
        },
    ]
    mock_api.get_version_localizations.return_value = [
        {
            "id": "vl1",
            "attributes": {
                "locale": "en-US",
                "description": "ASC Desc",
                "keywords": "asc,kw",
                "supportUrl": "https://s.asc",
                "marketingUrl": "https://m.asc",
            },
        },
    ]
    mock_api.get_screenshot_sets.return_value = {"data": [], "included": []}
    return mock_api


def test_listing_diff_requires_profile(client, tmp_path):
    p = tmp_path / "app.csv"
    p.write_text("locale,name\nen-US,Local\n", encoding="utf-8-sig")
    r = client.get("/api/listing/diff", params={"csv_path": str(p)})
    assert r.status_code == 400
    assert r.json()["ok"] is False


def test_listing_diff_returns_field_statuses(client, tmp_path):
    p = tmp_path / "app.csv"
    p.write_text(
        "locale,name,description\nen-US,Local Name,Same\n",
        encoding="utf-8-sig",
    )
    mock_api = _mock_asc_api_for_text()
    # Override description to match local for one equal field
    mock_api.get_version_localizations.return_value[0]["attributes"]["description"] = "Same"

    with patch("asc.web.routes_listing.Config", return_value=MagicMock()), \
         patch("asc.web.routes_listing.make_api_from_config", return_value=(mock_api, "app123")):
        r = client.get(
            "/api/listing/diff",
            params={"csv_path": str(p)},
            cookies={"asc_profile": "test"},
        )

    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["version"]["versionString"] == "1.2.0"
    assert "diff" in data
    locales = {x["locale"]: x for x in data["diff"]["locales"]}
    assert "en-US" in locales
    by_field = {f["field"]: f for f in locales["en-US"]["fields"]}
    assert by_field["name"]["status"] == "changed"
    assert by_field["name"]["local"] == "Local Name"
    assert by_field["name"]["asc"] == "ASC Name"
    assert by_field["description"]["status"] == "equal"


def test_listing_diff_no_editable_version_returns_4xx(client, tmp_path):
    p = tmp_path / "app.csv"
    p.write_text("locale,name\nen-US,Local\n", encoding="utf-8-sig")
    mock_api = MagicMock()
    mock_api.get_editable_version.return_value = None

    with patch("asc.web.routes_listing.Config", return_value=MagicMock()), \
         patch("asc.web.routes_listing.make_api_from_config", return_value=(mock_api, "app123")):
        r = client.get(
            "/api/listing/diff",
            params={"csv_path": str(p)},
            cookies={"asc_profile": "test"},
        )

    assert r.status_code in (400, 404, 409, 422)
    data = r.json()
    assert data["ok"] is False
    assert data.get("message") or data.get("error")


def test_listing_diff_merges_local_screenshots(client, tmp_path):
    from PIL import Image

    p = tmp_path / "app.csv"
    p.write_text("locale,name\nen-US,Local\n", encoding="utf-8-sig")
    shots = tmp_path / "screenshots" / "en-US"
    shots.mkdir(parents=True)
    img = shots / "01_home.png"
    Image.new("RGB", (1290, 2796), color=(10, 20, 30)).save(img)

    mock_api = _mock_asc_api_for_text()
    with patch("asc.web.routes_listing.Config", return_value=MagicMock()), \
         patch("asc.web.routes_listing.make_api_from_config", return_value=(mock_api, "app123")):
        r = client.get(
            "/api/listing/diff",
            params={"csv_path": str(p), "screenshots_dir": str(tmp_path / "screenshots")},
            cookies={"asc_profile": "test"},
        )

    assert r.status_code == 200
    data = r.json()
    locales = {x["locale"]: x for x in data["diff"]["locales"]}
    shot_types = {s["display_type"]: s for s in locales["en-US"]["screenshots"]}
    assert "APP_IPHONE_67" in shot_types
    assert len(shot_types["APP_IPHONE_67"]["local"]) == 1
    assert shot_types["APP_IPHONE_67"]["asc"] == []


def test_listing_pull_text_writes_selected_fields(client, tmp_path):
    p = tmp_path / "app.csv"
    p.write_text(
        "locale,name,subtitle,description\nen-US,Local,KeepMe,OldDesc\n",
        encoding="utf-8-sig",
    )
    mtime = p.stat().st_mtime
    mock_api = _mock_asc_api_for_text()

    with patch("asc.web.routes_listing.Config", return_value=MagicMock()), \
         patch("asc.web.routes_listing.make_api_from_config", return_value=(mock_api, "app123")):
        r = client.post(
            "/api/listing/pull/text",
            cookies={"asc_profile": "test"},
            json={
                "csv_path": str(p),
                "expected_mtime": mtime,
                "selections": [{"locale": "en-US", "fields": ["name", "description"]}],
            },
        )

    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["mtime"] > mtime
    text = p.read_text(encoding="utf-8-sig")
    assert "ASC Name" in text
    assert "ASC Desc" in text
    assert "KeepMe" in text  # unselected field preserved


def test_listing_pull_text_requires_profile(client, tmp_path):
    p = tmp_path / "app.csv"
    p.write_text("locale,name\nen-US,Local\n", encoding="utf-8-sig")
    r = client.post(
        "/api/listing/pull/text",
        json={
            "csv_path": str(p),
            "expected_mtime": p.stat().st_mtime,
            "selections": [{"locale": "en-US", "fields": ["name"]}],
        },
    )
    assert r.status_code == 400
    assert r.json()["ok"] is False


def test_listing_pull_text_conflict_returns_409(client, tmp_path):
    p = tmp_path / "app.csv"
    p.write_text("locale,name\nen-US,Local\n", encoding="utf-8-sig")
    mock_api = _mock_asc_api_for_text()

    with patch("asc.web.routes_listing.Config", return_value=MagicMock()), \
         patch("asc.web.routes_listing.make_api_from_config", return_value=(mock_api, "app123")):
        r = client.post(
            "/api/listing/pull/text",
            cookies={"asc_profile": "test"},
            json={
                "csv_path": str(p),
                "expected_mtime": 1.0,  # stale
                "selections": [{"locale": "en-US", "fields": ["name"]}],
            },
        )

    assert r.status_code == 409
    assert r.json()["ok"] is False


def test_listing_compare_and_overwrite_live_in_wizard():
    preview = Path("frontend/src/views/listing/PreviewStep.vue").read_text(encoding="utf-8")
    upload = Path("frontend/src/views/listing/UploadStep.vue").read_text(encoding="utf-8")
    dialog = Path("frontend/src/views/listing/ListingEditorDialog.vue").read_text(encoding="utf-8")
    workflow = Path("frontend/src/composables/useListingWorkflow.ts").read_text(encoding="utf-8")
    shared = Path("frontend/src/composables/useCompareSession.ts").read_text(encoding="utf-8")
    assert "/api/listing/compare" in workflow
    assert "createCompareSession" in workflow
    assert "waitForTaskResult" in shared
    assert "setTimeout(resolve, 250)" not in workflow
    assert "setTimeout(resolve, 250)" not in shared
    assert "listingOriginalUrl" in preview
    assert 'loading="lazy"' in preview
    assert "hydratedLocales" in preview
    assert 'ref("data/appstore_info.csv")' not in workflow
    assert 'ref("data/screenshots")' not in workflow
    assert "/api/listing/diff" not in preview
    assert "/api/listing/diff" not in upload
    assert "/api/listing/pull/text" in preview
    assert "write: false" in preview
    assert "write: false" in dialog
    assert "listing.overwrite_store" in dialog
    assert "listing.compare.button" in preview
    assert "listing.compare.button" in upload
    assert "useListingScope" in upload
    listing_dirty = workflow.split("function markDirty", 1)[1].split("function discard", 1)[0]
    assert "invalidateCompare" in listing_dirty
    iap = Path("frontend/src/composables/useIapWorkflow.ts").read_text(encoding="utf-8")
    iap_dirty = iap.split("function markDirty", 1)[1].split("function discard", 1)[0]
    assert "invalidateCompare" not in iap_dirty
    assert "JSON.stringify(textOnlySnapshot" in workflow
    assert "textOnlySnapshot" not in iap.split("function planCacheKey", 1)[1].split("function ", 1)[0]


def test_listing_diff_includes_asc_screenshots(client, tmp_path):
    p = tmp_path / "app.csv"
    p.write_text("locale,name\nen-US,Local\n", encoding="utf-8-sig")
    mock_api = _mock_asc_api_for_text()
    mock_api.get_screenshot_sets.return_value = {
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
                "fileName": "shot.png",
                "imageAsset": {"templateUrl": "https://cdn.example/{w}x{h}.png"},
            },
        }],
    }

    with patch("asc.web.routes_listing.Config", return_value=MagicMock()), \
         patch("asc.web.routes_listing.make_api_from_config", return_value=(mock_api, "app123")):
        r = client.get(
            "/api/listing/diff",
            params={"csv_path": str(p)},
            cookies={"asc_profile": "test"},
        )

    assert r.status_code == 200
    data = r.json()
    locales = {x["locale"]: x for x in data["diff"]["locales"]}
    shot_types = {s["display_type"]: s for s in locales["en-US"]["screenshots"]}
    assert "APP_IPHONE_67" in shot_types
    assert shot_types["APP_IPHONE_67"]["asc"][0]["remote_id"] == "s1"
    assert "100x100" in shot_types["APP_IPHONE_67"]["asc"][0]["thumb_url"]


def test_listing_asc_thumb_proxies_image(client):
    mock_api = MagicMock()
    mock_api.get.return_value = {
        "data": {
            "id": "s1",
            "attributes": {
                "imageAsset": {"templateUrl": "https://cdn.example/{w}x{h}.png"},
            },
        }
    }
    mock_resp = MagicMock()
    mock_resp.content = b"fake-png"
    mock_resp.headers = {"Content-Type": "image/png"}
    mock_resp.raise_for_status = MagicMock()

    with patch("asc.web.routes_listing.Config", return_value=MagicMock()), \
         patch("asc.web.routes_listing.make_api_from_config", return_value=(mock_api, "app123")), \
         patch("asc.web.routes_listing.requests.get", return_value=mock_resp) as get_mock:
        r = client.get(
            "/api/listing/asc-thumb",
            params={"screenshot_id": "s1"},
            cookies={"asc_profile": "test"},
        )

    assert r.status_code == 200
    assert r.content == b"fake-png"
    assert "100x100" in get_mock.call_args.args[0]


def test_listing_asc_thumb_requires_profile(client):
    r = client.get("/api/listing/asc-thumb", params={"screenshot_id": "s1"})
    assert r.status_code == 400
    assert r.json()["ok"] is False


def test_listing_pull_screenshots_starts_task(client, tmp_path):
    from asc.web import routes_api

    shots = tmp_path / "screenshots"
    shots.mkdir()
    mock_api = _mock_asc_api_for_text()

    with patch("asc.web.routes_listing.Config", return_value=MagicMock()), \
         patch("asc.web.routes_listing.make_api_from_config", return_value=(mock_api, "app123")), \
         patch("asc.web.routes_listing.download_asc_screenshots") as dl:
        r = client.post(
            "/api/listing/pull/screenshots",
            cookies={"asc_profile": "test"},
            json={
                "screenshots_dir": str(shots),
                "scopes": [{"locale": "en-US", "display_type": "APP_IPHONE_67"}],
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["task_id"]
        task = _wait_for_task(routes_api, data["task_id"])
        assert task is not None
        assert task["status"] == TaskStatus.DONE
        dl.assert_called_once()
        args = dl.call_args
        assert args.args[1] == "app123"
        assert args.args[2] == str(shots)
        assert args.args[3] == [{"locale": "en-US", "display_type": "APP_IPHONE_67"}]


def test_listing_pull_screenshots_requires_profile(client, tmp_path):
    r = client.post(
        "/api/listing/pull/screenshots",
        json={
            "screenshots_dir": str(tmp_path),
            "scopes": [{"locale": "en-US", "display_type": "APP_IPHONE_67"}],
        },
    )
    assert r.status_code == 400
    assert r.json()["ok"] is False


def test_listing_blocking_routes_offload_event_loop():
    """ASC/CDN listing probes must not block the async event loop."""
    import inspect
    from asc.web import routes_listing

    assert not inspect.iscoroutinefunction(routes_listing.listing_diff)
    assert not inspect.iscoroutinefunction(routes_listing.listing_asc_thumb)
    assert not inspect.iscoroutinefunction(routes_listing.listing_asc_image)
    pull_src = inspect.getsource(routes_listing.listing_pull_text)
    assert "to_thread" in pull_src
    assert "_do_listing_pull_text" in pull_src
    screenshot_pull_src = inspect.getsource(routes_listing.listing_pull_screenshots)
    assert "to_thread" in screenshot_pull_src
    assert "_start_listing_pull_screenshots_task" in screenshot_pull_src
    assert inspect.iscoroutinefunction(routes_listing.listing_compare)
    assert inspect.iscoroutinefunction(routes_listing.listing_translate)
    compare_src = inspect.getsource(routes_listing.listing_compare)
    assert "to_thread" in compare_src
    starter = inspect.getsource(routes_listing._start_listing_compare_task)
    assert "start_background_task" in starter
    assert 'kind="listing-compare"' in starter
    assert "reporter.set_phases" in starter
    translate_src = inspect.getsource(routes_listing.listing_translate)
    assert "to_thread" in translate_src


def test_listing_pull_text_write_false_keeps_csv(client, tmp_path):
    p = tmp_path / "app.csv"
    original = "locale,name,subtitle\nen-US,Local,KeepMe\n"
    p.write_text(original, encoding="utf-8-sig")
    before = p.read_bytes()
    mock_api = _mock_asc_api_for_text()

    with patch("asc.web.routes_listing.Config", return_value=MagicMock()), \
         patch("asc.web.routes_listing.make_api_from_config", return_value=(mock_api, "app123")):
        r = client.post(
            "/api/listing/pull/text",
            cookies={"asc_profile": "test"},
            json={"csv_path": str(p), "write": False},
        )

    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["written"] is False
    assert p.read_bytes() == before
    locales = {row["locale"]: row for row in data["snapshot"]["locales"]}
    assert locales["en-US"]["fields"]["name"] == "ASC Name"
    assert locales["en-US"]["fields"]["subtitle"] == "ASC Sub"


def test_listing_translate_returns_in_request(client):
    mock_config = MagicMock()
    mock_config.llm_api_key = "sk-test"
    mock_config.llm_base_url = "https://example.com"
    mock_config.llm_model = "gpt"
    translator = MagicMock()
    translator.translate_fields.return_value = {
        "locale": "zh-Hans",
        "name": "金币",
        "subtitle": "副标题",
        "keywords": "金币,游戏",
        "description": "立即获得金币。",
    }
    with patch("asc.web.routes_listing.Config", return_value=mock_config), patch(
        "asc.web.routes_listing.make_listing_translator", return_value=translator
    ):
        resp = client.post(
            "/api/listing/translate",
            cookies={"asc_profile": "test"},
            json={
                "source_locale": "en-US",
                "mode": "translate",
                "fields": [
                    {
                        "locale": "zh-Hans",
                        "name": "Coins",
                        "subtitle": "Tagline",
                        "keywords": "coins,game",
                        "description": "Get coins.",
                    }
                ],
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "task_id" not in data
    assert data["translations"][0]["name"] == "金币"
    translator.translate_fields.assert_called_once()
    kwargs = translator.translate_fields.call_args.kwargs
    assert kwargs["mode"] == "translate"
    assert kwargs["target_locale"] == "zh-Hans"


def test_listing_translate_without_llm_key_returns_400(client):
    mock_config = MagicMock()
    mock_config.llm_api_key = ""
    with patch("asc.web.routes_listing.Config", return_value=mock_config):
        resp = client.post(
            "/api/listing/translate",
            cookies={"asc_profile": "test"},
            json={
                "source_locale": "en-US",
                "fields": [{"locale": "zh-Hans", "name": "Coins", "description": "x"}],
            },
        )
    assert resp.status_code == 400
    assert "api_key" in json.dumps(resp.json())


def test_listing_compare_is_async_task(client, tmp_path):
    from asc.web import routes_listing

    p = tmp_path / "app.csv"
    p.write_text("locale,name\nen-US,Local Name\n", encoding="utf-8-sig")
    mock_api = _mock_asc_api_for_text()

    with patch("asc.web.routes_listing.Config", return_value=MagicMock()), \
         patch("asc.web.routes_listing.make_api_from_config", return_value=(mock_api, "app123")):
        resp = client.post(
            "/api/listing/compare",
            cookies={"asc_profile": "test"},
            json={"csv_path": str(p)},
        )
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]
        task = None
        for _ in range(100):
            task = routes_listing.task_store.get(task_id)
            if task and task["status"] in {TaskStatus.DONE, TaskStatus.ERROR, TaskStatus.CANCELED}:
                break
            time.sleep(0.02)

    assert task is not None
    assert task["status"] == TaskStatus.DONE
    assert task["kind"] == "listing-compare"
    result = task["result"]
    assert result["ok"] is True
    by_locale = {row["locale"]: row for row in result["locales"]}
    assert by_locale["en-US"]["status"] == "changed"
    assert by_locale["en-US"]["missingScreenshots"] is True
    progress = task.get("progress") or {}
    assert progress.get("phase") == "done"
    assert int(progress.get("pct") or 0) == 100
    raw_logs = task.get("logs") or []
    texts = [row["message"] if isinstance(row, dict) else str(row) for row in raw_logs]
    assert "核对完成" in "\n".join(texts)
