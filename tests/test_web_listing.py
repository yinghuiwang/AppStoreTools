# tests/test_web_listing.py
"""Unit tests for metadata upload locale/field filtering via /api/metadata/run."""
from __future__ import annotations

import json
import time

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


def test_listing_local_missing_csv_returns_400(client, tmp_path):
    missing = tmp_path / "does-not-exist.csv"
    r = client.get(
        "/api/listing/local",
        params={"csv_path": str(missing)},
        cookies={"asc_profile": "test"},
    )
    assert r.status_code == 400


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


def test_metadata_page_has_screenshot_workbench_markup(client):
    r = client.get("/metadata")
    assert r.status_code == 200
    assert 'id="screenshot-scopes-json-input"' in r.text
    assert "wbReorderDrop" in r.text
    assert "wbTriggerReplace" in r.text
    assert "wbDeleteScreenshot" in r.text
    assert "wbTriggerAdd" in r.text
    # I3: selection remapped by index after reorder rename
    assert "selectedFlags" in r.text


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
