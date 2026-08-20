"""Tests for ASC IAP remote pull progress reporting."""
from __future__ import annotations

from threading import Event

from asc.iap.remote import pull_remote_snapshot
from asc.progress import ProcessCanceled


class _Recorder:
    def __init__(self) -> None:
        self.phases: list[str] = []
        self.updates: list[tuple[int, int, str | None]] = []

    def phase(self, phase_id: str) -> None:
        self.phases.append(phase_id)

    def progress(self, current: int, total: int, msg: str | None = None) -> None:
        self.updates.append((current, total, msg))


class _Api:
    def list_in_app_purchases(self, app_id: str):
        return [
            {
                "id": "iap1",
                "attributes": {
                    "productId": "com.app.coins",
                    "name": "Coins",
                    "inAppPurchaseType": "CONSUMABLE",
                },
            }
        ]

    def get_in_app_purchase_localizations(self, iap_id: str):
        return []

    def get_in_app_purchase_price_schedule(self, iap_id: str):
        return None

    def list_subscription_groups(self, app_id: str):
        return [
            {"id": "g1", "attributes": {"referenceName": "Premium"}},
        ]

    def list_subscription_group_localizations(self, group_id: str):
        return []

    def list_subscriptions(self, group_id: str):
        return [
            {
                "id": "sub1",
                "attributes": {
                    "productId": "com.app.premium.month",
                    "name": "Monthly",
                    "subscriptionPeriod": "ONE_MONTH",
                },
            }
        ]

    def list_subscription_localizations(self, sub_id: str):
        return []

    def list_subscription_prices(self, sub_id: str):
        return []

    def list_subscription_intro_offers(self, sub_id: str):
        return []


def test_pull_remote_snapshot_reports_iap_and_group_phases():
    reporter = _Recorder()
    snapshot = pull_remote_snapshot(_Api(), "app1", reporter=reporter)
    assert reporter.phases == ["iap", "groups"]
    assert any(msg and msg.startswith("IAP ") for _, _, msg in reporter.updates)
    assert any(msg and msg.startswith("订阅组 ") for _, _, msg in reporter.updates)
    assert snapshot["items"][0]["productId"] == "com.app.coins"
    assert snapshot["subscriptionGroups"][0]["referenceName"] == "Premium"


def test_pull_remote_snapshot_honors_cancel_event():
    cancel = Event()
    cancel.set()
    try:
        pull_remote_snapshot(_Api(), "app1", cancel_event=cancel)
    except ProcessCanceled:
        return
    raise AssertionError("expected ProcessCanceled")
