"""Local listing/IAP thumbnail cache and /api/listing/thumb resize."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image
from fastapi.testclient import TestClient

from asc.web.server import create_app
from asc.web.thumbs import (
    THUMB_DEFAULT_WIDTH,
    clamp_thumb_width,
    ensure_jpeg_thumb,
    guess_image_media_type,
    thumbs_cache_dir,
)


def _png(path: Path, size=(1290, 2796)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color=(10, 20, 30)).save(path)
    return path


def test_clamp_and_guess_image_type(tmp_path):
    assert clamp_thumb_width(-3) == 0
    assert clamp_thumb_width(320) == 320
    assert clamp_thumb_width(9999) == 1280
    assert guess_image_media_type(tmp_path / "shot.png") == "image/png"
    assert guess_image_media_type(tmp_path / "shot.jpg") == "image/jpeg"
    assert guess_image_media_type(tmp_path / "notes.txt") is None


def test_ensure_jpeg_thumb_resizes_and_reuses_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("ASC_THUMBS_CACHE", str(tmp_path / "cache"))
    source = _png(tmp_path / "en-US" / "01.png")
    first = ensure_jpeg_thumb(source, THUMB_DEFAULT_WIDTH)
    assert first.suffix == ".jpg"
    assert first.is_file()
    with Image.open(first) as im:
        assert im.width == THUMB_DEFAULT_WIDTH
        assert im.format == "JPEG"
    assert first.parent == thumbs_cache_dir()
    second = ensure_jpeg_thumb(source, THUMB_DEFAULT_WIDTH)
    assert second == first
    Image.new("RGB", (800, 1600), color=(1, 2, 3)).save(source)
    third = ensure_jpeg_thumb(source, THUMB_DEFAULT_WIDTH)
    assert third != first


def test_listing_thumb_resizes_when_w_given(tmp_path, monkeypatch):
    monkeypatch.setenv("ASC_THUMBS_CACHE", str(tmp_path / "cache"))
    shots = tmp_path / "screenshots"
    img_path = _png(shots / "en-US" / "01_a.png")
    original_size = img_path.stat().st_size
    client = TestClient(create_app())
    resp = client.get(
        "/api/listing/thumb",
        params={"path": str(img_path), "root": str(shots), "w": 320},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/jpeg")
    assert len(resp.content) < original_size
    with Image.open(BytesIO(resp.content)) as im:
        assert im.width == 320
        assert im.format == "JPEG"


def test_listing_thumb_without_w_keeps_original(tmp_path):
    shots = tmp_path / "screenshots"
    img_path = _png(shots / "en-US" / "01_a.png")
    client = TestClient(create_app())
    resp = client.get(
        "/api/listing/thumb",
        params={"path": str(img_path), "root": str(shots)},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/png")
    with Image.open(BytesIO(resp.content)) as im:
        assert im.size == (1290, 2796)


def test_listing_thumb_rejects_non_image(tmp_path):
    shots = tmp_path / "screenshots"
    shots.mkdir()
    note = shots / "note.txt"
    note.write_text("hello", encoding="utf-8")
    client = TestClient(create_app())
    resp = client.get(
        "/api/listing/thumb",
        params={"path": str(note), "root": str(shots)},
    )
    assert resp.status_code == 400
