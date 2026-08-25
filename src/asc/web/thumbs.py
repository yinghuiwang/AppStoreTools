"""On-disk JPEG thumbnails for local listing/IAP screenshot previews."""
from __future__ import annotations

import hashlib
import mimetypes
import os
from pathlib import Path

THUMB_DEFAULT_WIDTH = 320
THUMB_MAX_WIDTH = 1280
_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})
ALLOWED_IMAGE_TYPES = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/jpg",
        "image/webp",
        "image/gif",
    }
)


def thumbs_cache_dir() -> Path:
    override = (os.environ.get("ASC_THUMBS_CACHE") or "").strip()
    if override:
        return Path(override)
    xdg = (os.environ.get("XDG_CACHE_HOME") or "").strip()
    if xdg:
        return Path(xdg) / "asc" / "thumbs"
    return Path.home() / ".cache" / "asc" / "thumbs"


def clamp_thumb_width(width: int) -> int:
    return max(0, min(int(width or 0), THUMB_MAX_WIDTH))


def guess_image_media_type(path: Path) -> str | None:
    media, _ = mimetypes.guess_type(str(path))
    if media and media.split(";", 1)[0].lower() in ALLOWED_IMAGE_TYPES:
        return media
    suffix = path.suffix.lower()
    if suffix == ".png":
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".gif":
        return "image/gif"
    return None


def is_image_path(path: Path) -> bool:
    return path.suffix.lower() in _IMAGE_SUFFIXES or guess_image_media_type(path) is not None


def ensure_jpeg_thumb(source: Path, width: int) -> Path:
    """Return a cached JPEG whose longest display edge is `width` (no upscale)."""
    width = clamp_thumb_width(width)
    if width <= 0:
        raise ValueError("width must be positive")
    resolved = source.expanduser().resolve()
    stat = resolved.stat()
    key = hashlib.sha256(
        f"{resolved}|{stat.st_mtime_ns}|{stat.st_size}|{width}".encode()
    ).hexdigest()
    dest = thumbs_cache_dir() / f"{key}.jpg"
    if dest.is_file() and dest.stat().st_size > 0:
        return dest

    from PIL import Image

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.tmp")
    try:
        with Image.open(resolved) as im:
            rgb = im.convert("RGB")
            if rgb.width > width:
                height = max(1, round(rgb.height * width / rgb.width))
                rgb = rgb.resize((width, height), Image.Resampling.LANCZOS)
            rgb.save(tmp, "JPEG", quality=80, optimize=True)
        tmp.replace(dest)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise
    return dest
