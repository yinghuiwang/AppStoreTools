"""Upload-time IAP / subscription JSON validation.

Editor-oriented checks live in ``iap.local.validate_snapshot``. This module
covers the stricter rules required before talking to App Store Connect.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Optional

REVIEW_SCREENSHOT_WARNING_BYTES = 5 * 1024 * 1024
REVIEW_SCREENSHOT_EXTS = {".png", ".jpg", ".jpeg"}
VALID_PERIODS = {
    "ONE_WEEK",
    "ONE_MONTH",
    "TWO_MONTHS",
    "THREE_MONTHS",
    "SIX_MONTHS",
    "ONE_YEAR",
}
VALID_INTRO_MODES = {"FREE_TRIAL", "PAY_AS_YOU_GO", "PAY_UP_FRONT"}
VALID_PROMO_MODES = {"PAY_AS_YOU_GO", "PAY_UP_FRONT"}

WarnFn = Callable[[str], None]


class ValidationError(Exception):
    """Raised when subscription JSON config fails pre-flight validation."""


def _require(cond: Any, msg: str) -> None:
    if not cond:
        raise ValidationError(msg)


def _non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _valid_territory_id(value: Any) -> bool:
    return isinstance(value, str) and len(value.strip()) == 3 and value.strip().isalpha()


def _warn(message: str, warn: WarnFn | None) -> None:
    if warn is not None:
        warn(message)
        return
    print(message, file=sys.stderr, flush=True)


def resolve_review_screenshot(obj: dict, config_dir: Path) -> None:
    """Resolve relative review.screenshot path against config_dir (in-place)."""
    review = obj.get("review")
    if not isinstance(review, dict):
        return
    shot = review.get("screenshot")
    if not shot or not isinstance(shot, str):
        return
    path = Path(shot)
    if not path.is_absolute():
        review["screenshot"] = str(config_dir / path)


def validate_iap_item_price(item: dict, label: str) -> None:
    price = item.get("price")
    if price is None:
        return
    if not isinstance(price, dict):
        raise ValueError(f"{label}.price must be an object")

    has_price_point = _non_empty_str(price.get("pricePointId"))
    has_base_lookup = (
        _non_empty_str(price.get("baseTerritory"))
        and _non_empty_str(price.get("baseAmount"))
    )
    if not has_price_point and not has_base_lookup:
        raise ValueError(
            f"{label}.price requires either pricePointId or baseTerritory + baseAmount"
        )
    if has_price_point and not _non_empty_str(price.get("baseTerritory")):
        raise ValueError(f"{label}.price.baseTerritory required when pricePointId is set")
    if price.get("baseTerritory") is not None and not _valid_territory_id(
        price.get("baseTerritory")
    ):
        raise ValueError(
            f"{label}.price.baseTerritory must be a 3-letter territory id such as USA or CHN"
        )
    if price.get("territory") is not None and not _valid_territory_id(
        price.get("territory")
    ):
        raise ValueError(
            f"{label}.price.territory must be a 3-letter territory id such as USA or CHN"
        )


def validate_review_screenshot(
    item: dict,
    label: str,
    *,
    warn: WarnFn | None = None,
) -> Optional[Path]:
    review = item.get("review")
    if not isinstance(review, dict):
        return None
    shot = review.get("screenshot")
    if not shot:
        return None
    if not isinstance(shot, str) or not shot.strip():
        raise ValueError(f"{label}.review.screenshot path required")
    path = Path(shot)
    if not path.exists() or not path.is_file():
        raise ValueError(f"{label}.review.screenshot file not found: {shot}")
    if path.suffix.lower() not in REVIEW_SCREENSHOT_EXTS:
        raise ValueError(
            f"{label}.review.screenshot must be .png/.jpg/.jpeg, got {path.suffix}"
        )
    size = path.stat().st_size
    if size > REVIEW_SCREENSHOT_WARNING_BYTES:
        _warn(
            f"⚠️  {label}.review.screenshot exceeds 5MB ({size} bytes); "
            "continuing and leaving final validation to App Store Connect",
            warn,
        )
    return path


def validate_subscription_config(groups: list[dict]) -> None:
    _require(isinstance(groups, list), "subscriptionGroups must be a list")
    for gi, group in enumerate(groups):
        gtag = f"subscriptionGroups[{gi}]"
        _require(isinstance(group, dict), f"{gtag} must be an object")
        _require(
            _non_empty_str(group.get("referenceName")),
            f"{gtag}.referenceName is required (non-empty string)",
        )
        subs = group.get("subscriptions", [])
        _require(
            isinstance(subs, list) and subs,
            f"{gtag}.subscriptions must be a non-empty list",
        )
        for si, sub in enumerate(subs):
            _validate_subscription(sub, f"{gtag}.subscriptions[{si}]")


def _validate_subscription(sub: dict, tag: str) -> None:
    _require(isinstance(sub, dict), f"{tag} must be an object")
    _require(_non_empty_str(sub.get("productId")), f"{tag}.productId required")
    _require(_non_empty_str(sub.get("name")), f"{tag}.name required")
    period = sub.get("subscriptionPeriod")
    _require(
        period in VALID_PERIODS,
        f"{tag}.subscriptionPeriod must be one of {sorted(VALID_PERIODS)}, got {period!r}",
    )
    _require(
        isinstance(sub.get("groupLevel"), int) and sub["groupLevel"] >= 1,
        f"{tag}.groupLevel must be a positive int",
    )
    locs = sub.get("localizations")
    _require(
        isinstance(locs, dict) and locs,
        f"{tag}.localizations required (at least 1 locale)",
    )
    for locale, loc in locs.items():
        ltag = f"{tag}.localizations[{locale}]"
        _require(isinstance(loc, dict), f"{ltag} must be an object")
        _require(_non_empty_str(loc.get("name")), f"{ltag}.name required")
        _require(_non_empty_str(loc.get("description")), f"{ltag}.description required")
    price = sub.get("price")
    _require(isinstance(price, dict), f"{tag}.price required (object)")
    has_price_point = _non_empty_str(price.get("pricePointId"))
    has_base_lookup = (
        _non_empty_str(price.get("baseTerritory"))
        and _non_empty_str(price.get("baseAmount"))
    )
    _require(
        has_price_point or has_base_lookup,
        f"{tag}.price requires either pricePointId or baseTerritory + baseAmount",
    )
    if price.get("baseTerritory") is not None:
        _require(
            _valid_territory_id(price.get("baseTerritory")),
            f"{tag}.price.baseTerritory must be a 3-letter territory id such as USA or CHN",
        )
    if price.get("territory") is not None:
        _require(
            _valid_territory_id(price.get("territory")),
            f"{tag}.price.territory must be a 3-letter territory id such as USA or CHN",
        )
    review = sub.get("review")
    _require(isinstance(review, dict), f"{tag}.review required (object)")
    shot = review.get("screenshot")
    _require(_non_empty_str(shot), f"{tag}.review.screenshot path required")
    shot_path = Path(shot)
    _require(
        shot_path.exists() and shot_path.is_file(),
        f"{tag}.review.screenshot file not found: {shot}",
    )
    _require(
        shot_path.suffix.lower() in REVIEW_SCREENSHOT_EXTS,
        f"{tag}.review.screenshot must be .png/.jpg/.jpeg, got {shot_path.suffix}",
    )
    size = shot_path.stat().st_size
    if size > REVIEW_SCREENSHOT_WARNING_BYTES:
        _warn(
            f"⚠️  {tag}.review.screenshot exceeds 5MB ({size} bytes); "
            "continuing and leaving final validation to App Store Connect",
            None,
        )
    intro = sub.get("introductoryOffer")
    if intro is not None:
        _validate_intro_offer(intro, f"{tag}.introductoryOffer")
    promos = sub.get("promotionalOffers", [])
    if promos:
        _require(isinstance(promos, list), f"{tag}.promotionalOffers must be a list")
        codes_seen: set[str] = set()
        for pi, promo in enumerate(promos):
            ptag = f"{tag}.promotionalOffers[{pi}]"
            _validate_promo_offer(promo, ptag)
            code = promo["offerCode"]
            _require(
                code not in codes_seen,
                f"{ptag}.offerCode={code!r} duplicates another on this subscription",
            )
            codes_seen.add(code)


def _validate_intro_offer(offer: dict, tag: str) -> None:
    _require(isinstance(offer, dict), f"{tag} must be an object")
    mode = offer.get("offerMode")
    _require(
        mode in VALID_INTRO_MODES,
        f"{tag}.offerMode must be one of {sorted(VALID_INTRO_MODES)}",
    )
    _require(_non_empty_str(offer.get("baseTerritory")), f"{tag}.baseTerritory required")
    _require(
        _valid_territory_id(offer.get("baseTerritory")),
        f"{tag}.baseTerritory must be a 3-letter territory id such as USA or CHN",
    )
    _require(
        offer.get("duration") in VALID_PERIODS,
        f"{tag}.duration must be one of {sorted(VALID_PERIODS)}",
    )
    _require(
        isinstance(offer.get("numberOfPeriods"), int) and offer["numberOfPeriods"] >= 1,
        f"{tag}.numberOfPeriods must be positive int",
    )
    if mode != "FREE_TRIAL":
        _require(
            _non_empty_str(offer.get("baseAmount")),
            f"{tag}.baseAmount required for non-FREE_TRIAL",
        )


def _validate_promo_offer(offer: dict, tag: str) -> None:
    _require(isinstance(offer, dict), f"{tag} must be an object")
    _require(_non_empty_str(offer.get("referenceName")), f"{tag}.referenceName required")
    _require(_non_empty_str(offer.get("offerCode")), f"{tag}.offerCode required")
    _require(
        offer.get("offerMode") in VALID_PROMO_MODES,
        f"{tag}.offerMode must be one of {sorted(VALID_PROMO_MODES)}",
    )
    _require(
        offer.get("duration") in VALID_PERIODS,
        f"{tag}.duration must be one of {sorted(VALID_PERIODS)}",
    )
    _require(
        isinstance(offer.get("numberOfPeriods"), int) and offer["numberOfPeriods"] >= 1,
        f"{tag}.numberOfPeriods must be positive int",
    )
    _require(_non_empty_str(offer.get("baseTerritory")), f"{tag}.baseTerritory required")
    _require(_non_empty_str(offer.get("baseAmount")), f"{tag}.baseAmount required")
