# Screenshots and previews

keywords: screenshot preview 截图 规格 DISPLAY_TYPE APP_IPHONE_67 6.9 6.5 iPad 13 10 images jpeg png

## Official rules

- **1–10** images per device size per localization.
- Formats: `.jpeg` / `.jpg` / `.png`. **No alpha / transparency**.
- App preview: optional, **up to 3** per localization per device size.
- Highest-resolution set can scale down to smaller sizes if UI is the same.

Sources:
- https://developer.apple.com/help/app-store-connect/manage-app-information/upload-app-previews-and-screenshots
- https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications/

Release-notes (2026): only **one iPhone set (6.5" or 6.9")** and **one iPad set (13")** are required; other sizes optional.
https://developer.apple.com/help/app-store-connect/release-notes/

## iPhone sizes (official) ↔ this tool `DISPLAY_TYPE_BY_SIZE`

| Official display | Official pixels (portrait) | Tool display type | In `constants.py`? |
| --- | --- | --- | --- |
| 6.9" | 1320×2868, 1290×2796, **1260×2736** | `APP_IPHONE_67` for 1320/1290 | 1260×2736 **not mapped** |
| 6.5" | 1284×2778, 1242×2688 | `APP_IPHONE_65` | yes |
| 6.3" | 1179×2556, **1206×2622** | `APP_IPHONE_61` for 1179 | 1206×2622 **not mapped** |
| 6.1" | 1170×2532, 1125×2436, **1080×2340** | `APP_IPHONE_61` / `APP_IPHONE_58` | 1080×2340 **not mapped** |
| 5.5" | 1242×2208 | `APP_IPHONE_55` | yes |
| 4.7" | 750×1334 | `APP_IPHONE_47` | yes |

Landscape = swapped dimensions. Tool maps both orientations.

Note: Apple now lists 1320×2868 / 1290×2796 under **6.9"**. This tool still labels them `APP_IPHONE_67`. When talking to users, say 6.9"/6.7" iPhone; when writing API/tool values, use `APP_IPHONE_67` unless ASC returns a newer type.

## iPad (official) ↔ tool

| Official display | Official pixels | Tool type | In constants? |
| --- | --- | --- | --- |
| 13" (required if iPad) | 2064×2752, 2048×2732 | `APP_IPAD_PRO_129` / `APP_IPAD_PRO_3GEN_129` | yes |
| 12.9" (2nd gen) | 2048×2732 | `APP_IPAD_PRO_3GEN_129` | yes |
| 11" | 1668×2388, plus 1488×2266 / 1668×2420 / 1640×2360 | `APP_IPAD_PRO_3GEN_11` for 1668×2388 | other 11" sizes **not mapped** |

Mac / Apple TV / Vision Pro / Watch sizes exist officially. This iOS-focused tool does **not** map them in `DISPLAY_TYPE_BY_SIZE`.

## Folder layout (this tool)

`data/screenshots/<folder>/` — PNG/JPG, sort by filename number for order.

Folder → locale: see locales.md (`cn` → `zh-Hans`, `en` → `en-US`, …). Unknown folder names should be official locale codes (`zh-Hans`, `pt-PT`).

## This tool behavior (not Apple)

- Upload **deletes all existing screenshots** for that `screenshotDisplayType` on the localization, then uploads local files.
- Device type is inferred from **pixel size**, not filename.
- Unmapped sizes are skipped / fail detection — do not tell the user “Apple rejects this size” if it is on the official spec but missing from `constants.py`.
