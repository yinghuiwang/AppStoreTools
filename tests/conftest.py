"""Shared test fixtures."""
from __future__ import annotations

import pytest


class FakeAPI:
    """In-memory mock of AppStoreConnectAPI covering subscription endpoints."""

    def __init__(self):
        self.groups = {}
        self.group_locs = {}
        self.subs = {}
        self.sub_locs = {}
        self.prices = {}
        self.intro_offers = {}
        self.promo_offers = {}
        self.review_shots = {}
        self.price_points = {}
        self.calls = []
        self._next = 1000

    def _nid(self, prefix):
        self._next += 1
        return f"{prefix}_{self._next}"

    # Groups
    def list_subscription_groups(self, app_id):
        self.calls.append(("list_subscription_groups", app_id))
        return [
            {"id": gid, "attributes": {"referenceName": g["referenceName"]}}
            for gid, g in self.groups.items() if g["appId"] == app_id
        ]

    def create_subscription_group(self, app_id, reference_name):
        self.calls.append(("create_subscription_group", app_id, reference_name))
        gid = self._nid("grp")
        self.groups[gid] = {"referenceName": reference_name, "appId": app_id}
        self.group_locs[gid] = {}
        return {"data": {"id": gid, "attributes": {"referenceName": reference_name}}}

    def update_subscription_group(self, group_id, attrs):
        self.calls.append(("update_subscription_group", group_id, attrs))
        self.groups[group_id].update(attrs)

    def list_subscription_group_localizations(self, group_id):
        return [
            {"id": loc["id"], "attributes": {"locale": locale, "name": loc["name"],
                                             "customAppName": loc.get("customAppName")}}
            for locale, loc in self.group_locs.get(group_id, {}).items()
        ]

    def create_subscription_group_localization(self, group_id, locale, name, custom_app_name=None):
        self.calls.append(("create_subscription_group_localization", group_id, locale))
        lid = self._nid("gloc")
        self.group_locs.setdefault(group_id, {})[locale] = {
            "id": lid, "name": name, "customAppName": custom_app_name,
        }
        return {"data": {"id": lid}}

    def update_subscription_group_localization(self, loc_id, attrs):
        self.calls.append(("update_subscription_group_localization", loc_id, attrs))

    # Subscriptions
    def list_subscriptions(self, group_id):
        return [
            {"id": sid, "attributes": s["attrs"]}
            for sid, s in self.subs.items() if s["groupId"] == group_id
        ]

    def create_subscription(self, group_id, attrs):
        self.calls.append(("create_subscription", group_id, attrs))
        sid = self._nid("sub")
        self.subs[sid] = {"groupId": group_id, "attrs": dict(attrs)}
        self.sub_locs[sid] = {}
        self.prices[sid] = []
        self.intro_offers[sid] = []
        self.promo_offers[sid] = []
        self.review_shots[sid] = []
        return {"data": {"id": sid, "attributes": attrs}}

    def update_subscription(self, sub_id, attrs):
        self.calls.append(("update_subscription", sub_id, attrs))
        self.subs[sub_id]["attrs"].update(attrs)

    def list_subscription_localizations(self, sub_id):
        return [
            {"id": loc["id"], "attributes": {"locale": locale, "name": loc["name"],
                                             "description": loc["description"]}}
            for locale, loc in self.sub_locs.get(sub_id, {}).items()
        ]

    def create_subscription_localization(self, sub_id, locale, name, description):
        self.calls.append(("create_subscription_localization", sub_id, locale))
        lid = self._nid("sloc")
        self.sub_locs.setdefault(sub_id, {})[locale] = {
            "id": lid, "name": name, "description": description,
        }
        return {"data": {"id": lid}}

    def update_subscription_localization(self, loc_id, attrs):
        self.calls.append(("update_subscription_localization", loc_id, attrs))

    # Price
    def find_subscription_price_point(self, sub_id, territory, amount):
        self.calls.append(("find_subscription_price_point", sub_id, territory, amount))
        for pp in self.price_points.get(sub_id, []):
            if pp["territory"] == territory and pp["customerPrice"] == amount:
                return pp["id"]
        return None

    def create_subscription_price(self, sub_id, price_point_id, territory, start_date=None):
        self.calls.append(("create_subscription_price", sub_id, price_point_id, territory))
        pid = self._nid("price")
        self.prices.setdefault(sub_id, []).append(
            {"id": pid, "pricePointId": price_point_id, "territory": territory}
        )
        return {"data": {"id": pid}}

    def list_subscription_prices(self, sub_id):
        return [{"id": p["id"], "attributes": {}} for p in self.prices.get(sub_id, [])]

    def delete_subscription_price(self, price_id):
        self.calls.append(("delete_subscription_price", price_id))
        for sid, plist in self.prices.items():
            self.prices[sid] = [p for p in plist if p["id"] != price_id]

    # Intro offers
    def list_subscription_intro_offers(self, sub_id):
        return [{"id": o["id"], "attributes": o} for o in self.intro_offers.get(sub_id, [])]

    def create_subscription_intro_offer(self, sub_id, attrs, price_point_id=None, territory=None):
        self.calls.append(("create_subscription_intro_offer", sub_id, attrs, price_point_id, territory))
        oid = self._nid("intro")
        self.intro_offers.setdefault(sub_id, []).append({"id": oid, **attrs})
        return {"data": {"id": oid}}

    def delete_subscription_intro_offer(self, offer_id):
        self.calls.append(("delete_subscription_intro_offer", offer_id))
        for sid, olist in self.intro_offers.items():
            self.intro_offers[sid] = [o for o in olist if o["id"] != offer_id]

    # Promo offers
    def list_subscription_promo_offers(self, sub_id):
        return [{"id": o["id"], "attributes": dict(o)} for o in self.promo_offers.get(sub_id, [])]

    def create_subscription_promo_offer(self, sub_id, attrs, price_point_id):
        self.calls.append(("create_subscription_promo_offer", sub_id, attrs, price_point_id))
        oid = self._nid("promo")
        self.promo_offers.setdefault(sub_id, []).append({"id": oid, **attrs})
        return {"data": {"id": oid}}

    def update_subscription_promo_offer(self, offer_id, attrs):
        self.calls.append(("update_subscription_promo_offer", offer_id, attrs))

    def delete_subscription_promo_offer(self, offer_id):
        self.calls.append(("delete_subscription_promo_offer", offer_id))
        for sid, olist in self.promo_offers.items():
            self.promo_offers[sid] = [o for o in olist if o["id"] != offer_id]

    # Review screenshots
    def list_subscription_review_screenshots(self, sub_id):
        return [{"id": s["id"], "attributes": s} for s in self.review_shots.get(sub_id, [])]

    def create_subscription_review_screenshot_reservation(self, sub_id, filename, filesize):
        self.calls.append(("create_subscription_review_screenshot_reservation",
                           sub_id, filename, filesize))
        sid = self._nid("shot")
        self.review_shots.setdefault(sub_id, []).append(
            {"id": sid, "fileName": filename, "uploaded": False}
        )
        return {"data": {"id": sid, "attributes": {"uploadOperations": []}}}

    def upload_subscription_review_screenshot(self, upload_operations, file_bytes):
        self.calls.append(("upload_subscription_review_screenshot", len(file_bytes)))

    def commit_subscription_review_screenshot(self, screenshot_id, source_file_checksum):
        self.calls.append(("commit_subscription_review_screenshot", screenshot_id))
        for sid, slist in self.review_shots.items():
            for s in slist:
                if s["id"] == screenshot_id:
                    s["uploaded"] = True

    def delete_subscription_review_screenshot(self, screenshot_id):
        self.calls.append(("delete_subscription_review_screenshot", screenshot_id))
        for sid, slist in self.review_shots.items():
            self.review_shots[sid] = [s for s in slist if s["id"] != screenshot_id]

    # Also need list_subscription_price_points for price-not-found tests
    def list_subscription_price_points(self, sub_id, territory):
        return []


@pytest.fixture
def fake_api():
    return FakeAPI()


@pytest.fixture
def tmp_png(tmp_path):
    """Return path to a valid small PNG file (1x1 red pixel)."""
    png_bytes = bytes.fromhex(
        "89504E470D0A1A0A0000000D49484452000000010000000108020000"
        "00907753DE0000000C4944415408D76368F8CF000000030001013C90"
        "B8120000000049454E44AE426082"
    )
    p = tmp_path / "shot.png"
    p.write_bytes(png_bytes)
    return p
