# Languages and locales

keywords: locale language region 语言 地区 zh-Hans en-US ar-SA pt-BR es-MX CSV folder constants 50 Bangla Gujarati

## Official count (2026)

App Store metadata can be localized in **50 languages** (was 39; +11 on 2026-03-31).
Source: https://developer.apple.com/news/?id=97t4mt64

Help list (language names): https://developer.apple.com/help/app-store-connect/reference/app-information/app-store-localizations

API shortcodes (use these in CSV / ASC API): https://developer.apple.com/documentation/appstoreconnectapi/managing-metadata-in-your-app-by-using-locale-shortcodes

Official help names “Bangla / Odia / Slovenia”; API table uses “Bengali / Oriya / Slovenian”. Same 50 locales — **use the shortcodes below**.

## ASC locale shortcodes (authoritative)

| Language (help / API) | locale |
| --- | --- |
| Arabic | ar-SA |
| Bangla / Bengali | bn-BD |
| Catalan | ca |
| Chinese (Simplified) | zh-Hans |
| Chinese (Traditional) | zh-Hant |
| Croatian | hr |
| Czech | cs |
| Danish | da |
| Dutch | nl-NL |
| English (Australia) | en-AU |
| English (Canada) | en-CA |
| English (U.K.) | en-GB |
| English (U.S.) | en-US |
| Finnish | fi |
| French | fr-FR |
| French (Canada) | fr-CA |
| German | de-DE |
| Greek | el |
| Gujarati | gu-IN |
| Hebrew | he |
| Hindi | hi |
| Hungarian | hu |
| Indonesian | id |
| Italian | it |
| Japanese | ja |
| Kannada | kn-IN |
| Korean | ko |
| Malay | ms |
| Malayalam | ml-IN |
| Marathi | mr-IN |
| Norwegian | no |
| Odia / Oriya | or-IN |
| Polish | pl |
| Portuguese (Brazil) | pt-BR |
| Portuguese (Portugal) | pt-PT |
| Punjabi | pa-IN |
| Romanian | ro |
| Russian | ru |
| Slovak | sk |
| Slovenian | sl-SI |
| Spanish (Mexico) | es-MX |
| Spanish (Spain) | es-ES |
| Swedish | sv |
| Tamil | ta-IN |
| Telugu | te-IN |
| Thai | th |
| Turkish | tr |
| Ukrainian | uk |
| Urdu | ur-PK |
| Vietnamese | vi |

Added 2026-03-31: bn-BD, gu-IN, kn-IN, ml-IN, mr-IN, or-IN, pa-IN, sl-SI, ta-IN, te-IN, ur-PK.

## Which localization a customer sees

Depends on App Store language for their storefront, device language, languages you added, and the app’s **primary language**. If nothing matches, Apple falls back to the next relevant localization, then primary.
Source: https://developer.apple.com/help/app-store-connect/manage-app-information/localize-app-store-information

Metadata languages ≠ Xcode binary localizations.

When you add a language, screenshots and most fields copy from primary; **description and keywords do not**.

## This tool: CSV / folder aliases (`constants.py`)

`constants.py` is an **alias table**, not the official 50-locale list. Prefer the official shortcodes above.

CSV aliases (`CSV_LOCALE_TO_ASC`):
- `en` → `en-US`
- `ar` → `ar-SA`
- `zh-Hans` / `zh-Hant` stay
- `ja` / `ko` stay
- `fr` → `fr-FR`
- `de` → `de-DE`
- `es` → `es-ES`
- `pt` / `pt-BR` → `pt-BR`

Screenshot folder aliases (`SCREENSHOT_FOLDER_TO_LOCALE`):
- `cn` / `zh` / `zh-hans` → `zh-Hans`
- `en` → `en-US`
- `ja` / `ko` stay
- `fr` → `fr-FR`, `de` → `de-DE`, `es` → `es-ES`, `pt` → `pt-BR`

`normalize_locale_code()`: `_` → `-`; `zh-hans`/`zh-hant` casing; `xx-yy` → `xx-YY`.

**Not in constants (do not invent aliases):** `pt-PT`, `es-MX`, `en-GB`/`en-AU`/`en-CA`, `fr-CA`, all 11 new 2026 locales, and most European/Indic codes. Write the official shortcode in CSV `locale` and use a folder named that shortcode (or a mapped alias).

CSV `locale` also accepts `DisplayName(code)` such as `简体中文(zh-Hans)`.

## Skill vs official

`appstore-listing` skill defaults to **16** languages. Official store supports **50**. Extra languages are valid if the user asks; use official shortcodes, not skill-only names.
