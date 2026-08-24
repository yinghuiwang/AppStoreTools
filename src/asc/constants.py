"""Constants for App Store Connect API"""

from typing import Optional

BASE_URL = "https://api.appstoreconnect.apple.com"

DISPLAY_TYPE_BY_SIZE = {
    (1320, 2868): "APP_IPHONE_67",
    (2868, 1320): "APP_IPHONE_67",
    (1290, 2796): "APP_IPHONE_67",
    (2796, 1290): "APP_IPHONE_67",
    (1260, 2736): "APP_IPHONE_67",
    (2736, 1260): "APP_IPHONE_67",
    (1284, 2778): "APP_IPHONE_65",
    (2778, 1284): "APP_IPHONE_65",
    (1242, 2688): "APP_IPHONE_65",
    (2688, 1242): "APP_IPHONE_65",
    (1206, 2622): "APP_IPHONE_61",
    (2622, 1206): "APP_IPHONE_61",
    (1179, 2556): "APP_IPHONE_61",
    (2556, 1179): "APP_IPHONE_61",
    (1170, 2532): "APP_IPHONE_61",
    (2532, 1170): "APP_IPHONE_61",
    (1080, 2340): "APP_IPHONE_61",
    (2340, 1080): "APP_IPHONE_61",
    (1125, 2436): "APP_IPHONE_58",
    (2436, 1125): "APP_IPHONE_58",
    (1242, 2208): "APP_IPHONE_55",
    (2208, 1242): "APP_IPHONE_55",
    (750, 1334): "APP_IPHONE_47",
    (1334, 750): "APP_IPHONE_47",
    (2048, 2732): "APP_IPAD_PRO_3GEN_129",
    (2732, 2048): "APP_IPAD_PRO_3GEN_129",
    (1668, 2388): "APP_IPAD_PRO_3GEN_11",
    (2388, 1668): "APP_IPAD_PRO_3GEN_11",
    (1668, 2420): "APP_IPAD_PRO_3GEN_11",
    (2420, 1668): "APP_IPAD_PRO_3GEN_11",
    (1640, 2360): "APP_IPAD_PRO_3GEN_11",
    (2360, 1640): "APP_IPAD_PRO_3GEN_11",
    (1488, 2266): "APP_IPAD_PRO_3GEN_11",
    (2266, 1488): "APP_IPAD_PRO_3GEN_11",
    (2064, 2752): "APP_IPAD_PRO_129",
    (2752, 2064): "APP_IPAD_PRO_129",
}

SCREENSHOT_FOLDER_TO_LOCALE = {
    "cn": "zh-Hans",
    "zh": "zh-Hans",
    "zh-hans": "zh-Hans",
    "en": "en-US",
    "ja": "ja",
    "ko": "ko",
    "fr": "fr-FR",
    "de": "de-DE",
    "es": "es-ES",
    "pt": "pt-BR",
}

CSV_LOCALE_TO_ASC = {
    "en": "en-US",
    "ar": "ar-SA",
    "zh-Hans": "zh-Hans",
    "zh-Hant": "zh-Hant",
    "ja": "ja",
    "ko": "ko",
    "fr": "fr-FR",
    "de": "de-DE",
    "es": "es-ES",
    "pt-BR": "pt-BR",
    "pt": "pt-BR",
}


def normalize_locale_code(locale_code: str) -> str:
    """标准化 locale，兼容 CSV 中常见简写/大小写差异"""
    code = (locale_code or "").strip().strip('"').strip("'")
    if not code:
        return code
    code = code.replace("_", "-")
    lowered = code.lower()
    if lowered == "zh-hans":
        return "zh-Hans"
    if lowered == "zh-hant":
        return "zh-Hant"
    if len(code) == 2:
        return lowered
    if "-" in code:
        lang, region = code.split("-", 1)
        if len(lang) == 2 and len(region) == 2:
            return f"{lang.lower()}-{region.upper()}"
    return code


# Metadata CSV headers: English canonical (ASC API style) + Chinese aliases.
# Every key maps to its canonical name; unknown headers are rejected by canonicalize.
CSV_HEADER_ALIASES: dict[str, str] = {
    # canonical → self
    "locale": "locale",
    "name": "name",
    "subtitle": "subtitle",
    "description": "description",
    "keywords": "keywords",
    "supportUrl": "supportUrl",
    "marketingUrl": "marketingUrl",
    "privacyPolicyUrl": "privacyPolicyUrl",
    # Chinese aliases
    "语言": "locale",
    "应用名称": "name",
    "副标题": "subtitle",
    "长描述": "description",
    "描述": "description",
    "关键词": "keywords",
    "关键字": "keywords",
    "技术支持链接": "supportUrl",
    "技术支持网址": "supportUrl",
    "营销网站": "marketingUrl",
    "营销网址": "marketingUrl",
    "隐私政策网址": "privacyPolicyUrl",
    "隐私政策链接": "privacyPolicyUrl",
    "隐私政策URL": "privacyPolicyUrl",
}


def canonicalize_csv_header(raw: str) -> Optional[str]:
    """Map a CSV header to its canonical English key, or None if unknown."""
    if raw is None:
        return None
    cleaned = raw.strip().strip('"').strip("'").strip()
    if not cleaned:
        return None
    return CSV_HEADER_ALIASES.get(cleaned)
