#!/usr/bin/env bash
# Rebuild ASC Web UI static assets that are normally committed to git.
# Requires: curl, Node.js (npx). Network needed only when refreshing vendor/fonts.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

STATIC="$ROOT/src/asc/web/static"
VENDOR="$STATIC/vendor"
FONTS_DIR="$STATIC/fonts"

mkdir -p "$VENDOR" "$FONTS_DIR"

HTMX_VER="1.9.12"
ALPINE_VER="3.14.8"

if [[ "${1:-}" == "--refresh-vendor" ]]; then
  echo "Refreshing vendor JS..."
  curl -fsSL -o "$VENDOR/htmx-${HTMX_VER}.min.js" \
    "https://unpkg.com/htmx.org@${HTMX_VER}/dist/htmx.min.js"
  curl -fsSL -o "$VENDOR/alpine-${ALPINE_VER}.min.js" \
    "https://unpkg.com/alpinejs@${ALPINE_VER}/dist/cdn.min.js"
fi

echo "Building Tailwind CSS..."
npx --yes tailwindcss@3.4.17 \
  -c "$ROOT/src/asc/web/tailwind.config.js" \
  -i "$ROOT/src/asc/web/input.css" \
  -o "$STATIC/tailwind.css" \
  --minify

echo "Done: $STATIC/tailwind.css"
