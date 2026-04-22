"""Constants for App Store Connect API"""

BASE_URL = "https://api.appstoreconnect.apple.com"

DISPLAY_TYPE_BY_SIZE = {
    (1320, 2868): "APP_IPHONE_67",
    (2868, 1320): "APP_IPHONE_67",
    (1290, 2796): "APP_IPHONE_67",
    (2796, 1290): "APP_IPHONE_67",
    (1284, 2778): "APP_IPHONE_65",
    (2778, 1284): "APP_IPHONE_65",
    (1242, 2688): "APP_IPHONE_65",
    (2688, 1242): "APP_IPHONE_65",
    (1179, 2556): "APP_IPHONE_61",
    (2556, 1179): "APP_IPHONE_61",
    (1170, 2532): "APP_IPHONE_61",
    (2532, 1170): "APP_IPHONE_61",
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
