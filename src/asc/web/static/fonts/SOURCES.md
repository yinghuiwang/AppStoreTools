# Font sources

Fonts are downloaded from Google Fonts (SIL Open Font License 1.1).

Families used by ASC Web UI:
- DM Sans
- Fira Code
- Instrument Serif

Upstream CSS snapshot retrieved from fonts.googleapis.com (same family/weight query as the previous CDN link in `base.html`). Binary `.woff2` files were fetched from `fonts.gstatic.com` and are referenced by `../fonts.css` via `/static/fonts/...`.

Do not re-introduce CDN `@import` or absolute `fonts.gstatic.com` URLs in served CSS.
