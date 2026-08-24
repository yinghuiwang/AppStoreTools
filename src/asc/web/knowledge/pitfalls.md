# Common rejections and tool limits

keywords: rejection 拒审 tool limit no editable version delete screenshots create-only promotional text 100 bytes Guideline

## This tool (asc / web) — say these out loud

1. **Will not create an App Store version.** User must already have an editable version in App Store Connect.
2. **Screenshot upload deletes then replaces** every image in that `screenshotDisplayType` for the locale. Partial “add one shot” is not supported.
3. **IAP default is create-only for existing fields.** Missing localizations/prices/territories on an existing SKU are still created. `--update-existing` overwrites name/localizations/review shots; Apple cannot replace an IAP price schedule or availability, so those requests fail instead of reporting success.
4. **CSV has no promotional text / What’s New / copyright.** Promo text is 170 chars and can be edited in ASC without a new version; What’s New is a separate command (4000 chars).
5. **Territory IDs are 3 letters** (`USA`, `CHN`). `US` / `CN` fail validation.
6. **Price** needs `pricePointId` or `baseTerritory` + `baseAmount`.
7. **Unmapped screenshot pixels** fail the upload instead of being skipped. Official sizes such as 1260×2736 / 1206×2622 / 1080×2340 are mapped. Truly unknown sizes need `--display-type` or a constants update — that is not an Apple rejection.
8. **`constants.py` locale aliases are incomplete** vs official 50 locales. Prefer official shortcodes (`pt-PT`, `es-MX`, `bn-BD`, …).
9. Agent file tools only see the **user project** + form paths. Knowledge lives in this package — use `search_knowledge` / `get_knowledge`, never `read_file` on AppStoreTools sources.
10. `write_file` / `delete_file` cannot and must not edit this knowledge base.

## Frequent App Review / listing issues (official-aligned)

- Name/subtitle/keywords over **30 / 30 / 100**.
- Description over **4000**, or HTML/Markdown in the description.
- Missing **support URL** or privacy policy URL (iOS).
- Keywords that copy the app name, or name another app.
- Screenshots with transparency/alpha, or wrong pixel size.
- More than 10 screenshots per size.
- IAP display name not 2–30, description over 45, missing review screenshot.
- First IAP/subscription of a type submitted **without** a new app version.
- Subscription duration changed after review (not allowed).
- What’s New missing on an update (required after v1).
- Version not editable (`Ready for Distribution` without a new version) — uploads fail here.

Guideline reminders (not a full legal review): accurate metadata; subscriptions need clear auto-renew legal text (skill listing block is a template); China mainland games need NPPA approval / ICP where required.

## Skill vs official (quick)

| Claim | Official | Action |
| --- | --- | --- |
| Name/subtitle target ≤ 27 | Hard limit **30** | Buffer OK; never say 27 is Apple’s max |
| Keywords target ≤ 90 | **100 characters** (help also says 100 bytes) | Hard max 100 chars |
| 16 default languages | **50** locales | Skill subset only |
| Group display name 2–30 | Not stated on group page; IAP name **is** 2–30 | Conservative 2–30 |
| Description 400–600 words | **4000 characters** | Style vs cap |
