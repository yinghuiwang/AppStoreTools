# Listing metadata

keywords: listing metadata name subtitle keywords 字数 100 description promotional text what's new URL 30 100 170 4000 必填

Character counts below are **Apple official** unless marked skill/tool. CJK counts as 1 character in the ASC UI (same as Latin). Always count the actual string.

## Field limits (official)

| Field | Limit | Required | Localizable | Notes |
| --- | --- | --- | --- | --- |
| Name | **2–30** characters | Yes (app info) | Yes | Product page + install name |
| Subtitle | **≤ 30** characters | Optional | Yes | Under the name |
| Keywords | **100 characters** (help also says **100 bytes**) | Yes (version) | Yes | Comma-separated |
| Description | **4000** characters | Yes (version) | Yes | Plain text; **no HTML** |
| Promotional text | **170** characters | Optional | Yes | Above description; iOS 11+ |
| What’s New | **4000** characters | After first version | Yes | Not on the first version |
| Support URL | URL with protocol | Yes (version) | Yes | Must reach real contact info |
| Marketing URL | URL with protocol | Optional | Yes | |
| Privacy Policy URL | URL | Required for iOS/macOS | Yes (app info) | |

Sources (checked 2026-08):
- Name / subtitle: https://developer.apple.com/help/app-store-connect/reference/app-information/app-information
- Description / keywords / URLs / promotional text / What’s New: https://developer.apple.com/help/app-store-connect/reference/app-information/platform-version-information
- Product-page wording (30 / 30 / 100 chars / 170 promo): https://developer.apple.com/app-store/product-page/
- Search keyword tips: https://developer.apple.com/app-store/search/

### Keywords: 100 characters vs 100 bytes

- Product page + search docs: **100 characters**, commas, no spaces after commas; spaces allowed inside a phrase (`Real Estate`).
- Platform version help: **100 bytes**, each keyword **> 2 characters**.
- **Use 100 characters** (what the UI and marketing docs enforce). Do not exceed 100. CJK = 1. If a conservative check is needed, also keep UTF-8 ≤ 100 bytes.

Do not repeat app name, company name, or category. No other apps’ names. No `#` / `@` unless part of the brand. Promotional text **does not** affect search ranking.

### Promotional text

Can be updated **without** submitting a new version. This tool’s CSV **does not** include `promotionalText` — edit it in App Store Connect if needed.

### Description

Plain text + line breaks. Apple does not render Markdown (`**bold**`, headings). `- ` bullets are fine.

## This tool CSV

Canonical columns (`FIELD_NAMES` / `CSV_HEADER_ALIASES`):
`locale`, `name`, `subtitle`, `description`, `keywords`, `supportUrl`, `marketingUrl`, `privacyPolicyUrl`

Chinese aliases: 语言 / 应用名称 / 副标题 / 长描述|描述 / 关键词|关键字 / 技术支持网址|链接 / 营销网站|网址 / 隐私政策链接|网址|URL.

Not in CSV: promotional text, What’s New (use `whats-new` / web What’s New), copyright, review notes.

## Multi-language strategy

1. Pick a primary language in ASC (fallback for unmatched storefronts).
2. Localize name + subtitle + keywords + description + URLs per locale.
3. Keep the brand short name untranslated; translate only the tagline.
4. Validate **each** locale independently (DE/TH/AR/VI often grow past 30/100).
5. Official store has **50** locales — do not stop at a skill’s 16-language default.

## Skill vs official

`appstore-listing` skill:
- Targets **≤ 27 / ≤ 27 / ≤ 90** (90% of 30/30/100) — **writing buffer, not Apple’s hard limit**. Hard reject is still 30/30/100.
- Description “400–600 words” is a style target; official cap is **4000 characters**.
- Requires ToS + privacy + subscription URLs in the description legal block — useful for Guideline 3.1.2, not a listed ASC field limit.
- Separator rule (` - ` vs `: `) is a team convention, not Apple.

## Web 向导

三步：创建 → 预览 → 上传（`?step=create|preview|upload`）。旧 `?tab=local` 进预览，`?tab=diff|upload` 进上传。CSV / 截图路径只在创建步选择（标签旁 `?` 打开格式说明）；预览/上传只读沿用。商店拉取 `write:false` 只进内存。预览弹窗只改 7 个 CSV 字段；截图在语言卡片下立刻写盘。`csv_set_fields` 可追加 locale。`/api/listing/translate` 用商品页字数，不用 IAP 2–30/45。
