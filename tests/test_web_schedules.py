import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import plistlib
import pytest
from fastapi.testclient import TestClient

from asc.schedule import (
    ScheduleError,
    ScheduleLockTimeout,
    add_task,
    load_tasks,
    query_review as real_query_review,
)
from asc.web.server import create_app


class FakeHeartbeat:
    def __init__(self, system: str = "darwin"):
        self._system = system
        self.plist = None
        self.crontab = ""
        self.fail_bootstrap = False
        self.crontab_fail_times = 0
        self.bootouts = []
        self.bootstraps = []
        self._plist_path = Path("/tmp/LaunchAgents/com.asc.schedule.plist")
        self._log_path = Path("/tmp/asc-home/schedule-tick.log")

    def system(self):
        return self._system

    def uid(self):
        return 501

    def plist_path(self):
        return self._plist_path

    def log_path(self):
        return self._log_path

    def read_plist(self):
        return self.plist

    def write_plist(self, data: bytes):
        self.plist = data

    def remove_plist(self):
        self.plist = None

    def bootout(self, domain, plist):
        self.bootouts.append((domain, plist))

    def bootstrap(self, domain, plist):
        self.bootstraps.append((domain, plist))
        if self.fail_bootstrap:
            raise RuntimeError("bootstrap failed")

    def read_crontab(self):
        return self.crontab

    def write_crontab(self, text: str):
        if self.crontab_fail_times:
            self.crontab_fail_times -= 1
            self.crontab = text
            raise RuntimeError("crontab failed")
        self.crontab = text


def _lookup(name):
    return {"issuer_id": "", "key_id": "", "key_file": "", "app_id": ""}


@pytest.fixture
def scheduled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "schedules.toml"
    asc = tmp_path / "asc"
    asc.write_text("#!/bin/sh\n", encoding="utf-8")
    backend = FakeHeartbeat()
    monkeypatch.setattr("asc.schedule.default_schedule_path", lambda: path)
    monkeypatch.setattr("asc.schedule.default_profile_lookup", _lookup)
    monkeypatch.setattr("asc.schedule.query_review", lambda profile, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setenv("TZ", "Asia/Shanghai")
    from asc.web import routes_schedule

    monkeypatch.setattr(routes_schedule, "heartbeat_backend", lambda: backend)
    monkeypatch.setattr(routes_schedule, "asc_executable", lambda: asc.resolve())
    client = TestClient(create_app())
    return client, path, backend, asc


def test_schedule_routes_are_mounted():
    paths = [getattr(route, "path", "") for route in create_app().routes]
    assert "/api/schedules" in paths
    assert "/api/schedules/timezones" in paths
    assert "/api/schedules/heartbeat/install" in paths


def test_timezones_are_sorted_and_include_shanghai_and_utc(scheduled):
    client, _, _, _ = scheduled
    response = client.get("/api/schedules/timezones")
    assert response.status_code == 200
    names = response.json()["timezones"]
    assert names == sorted(names)
    assert "Asia/Shanghai" in names
    assert "UTC" in names
    assert all(not name.startswith(("posix/", "right/")) for name in names)


def test_invalid_timezone_is_400_on_create(scheduled, monkeypatch: pytest.MonkeyPatch):
    client, path, _, _ = scheduled

    def boom(**kwargs):
        raise AssertionError("capture_timezone should not run")

    monkeypatch.setattr("asc.schedule.capture_timezone", boom)
    zh = client.post(
        "/api/schedules",
        json={"profile": "myapp", "kind": "daily", "time": "09:30", "timezone": "Not/AZone"},
        cookies={"asc_lang": "zh"},
    )
    assert zh.status_code == 400
    assert zh.json() == {"error": "无效的 IANA 时区：Not/AZone"}
    en = client.post(
        "/api/schedules",
        json={"profile": "myapp", "kind": "daily", "time": "09:30", "timezone": "Not/AZone"},
        cookies={"asc_lang": "en"},
    )
    assert en.status_code == 400
    assert en.json() == {"error": "Invalid IANA time zone: Not/AZone"}
    assert not path.exists()


def test_explicit_timezone_persists_when_capture_fails(scheduled, monkeypatch: pytest.MonkeyPatch):
    client, path, _, _ = scheduled

    def boom(**kwargs):
        raise ScheduleError("timezone")

    monkeypatch.setattr("asc.schedule.capture_timezone", boom)
    created = client.post(
        "/api/schedules",
        json={"profile": "myapp", "kind": "daily", "time": "09:30", "timezone": "Asia/Shanghai"},
    )
    assert created.status_code == 200, created.text
    assert created.json()["timezone"] == "Asia/Shanghai"
    assert load_tasks(path)[0].timezone == "Asia/Shanghai"


def test_omitted_and_blank_timezone_use_capture(scheduled, monkeypatch: pytest.MonkeyPatch):
    client, path, _, _ = scheduled
    monkeypatch.setattr("asc.schedule.capture_timezone", lambda **kwargs: "Europe/Berlin")
    omitted = client.post("/api/schedules", json={"profile": "myapp", "kind": "daily", "time": "09:30"})
    assert omitted.status_code == 200, omitted.text
    assert omitted.json()["timezone"] == "Europe/Berlin"
    blank = client.post(
        "/api/schedules",
        json={"profile": "myapp", "kind": "daily", "time": "18:00", "timezone": ""},
    )
    assert blank.status_code == 200, blank.text
    assert [item.timezone for item in load_tasks(path)] == ["Europe/Berlin", "Europe/Berlin"]


def test_post_shares_the_schedule_file_and_lists_every_profile(scheduled):
    client, path, backend, asc = scheduled
    body = {"profile": "myapp", "kind": "daily", "time": "09:30"}
    assert "notify_kinds" not in body
    created = client.post("/api/schedules", json=body)
    assert created.status_code == 200
    task_id = created.json()["id"]
    assert load_tasks(path)[0].id == task_id
    listed = client.get("/api/schedules")
    assert listed.status_code == 200
    assert [item["profile"] for item in listed.json()["tasks"]] == ["myapp"]
    add_task(
        profile="other",
        kind="daily",
        time="18:00",
        schedule_path=path,
        now=datetime(2026, 10, 14, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        profile_lookup=_lookup,
        backend=backend,
        asc_path=asc.resolve(),
        environ={"TZ": "Asia/Shanghai"},
    )
    both = client.get("/api/schedules")
    assert [item["profile"] for item in both.json()["tasks"]] == ["myapp", "other"]
    assert "interval_hours" not in both.json()["tasks"][0]
    assert both.json()["tasks"][0]["watch"] == "app_store"
    deleted = client.delete(f"/api/schedules/{task_id}")
    assert deleted.status_code == 200
    assert task_id not in [item.id for item in load_tasks(path)]
    assert backend.plist is not None


def test_string_enabled_is_400_in_both_languages(scheduled):
    client, path, _, _ = scheduled
    zh = client.post(
        "/api/schedules",
        json={"profile": "myapp", "kind": "daily", "time": "09:30", "enabled": "true"},
        cookies={"asc_lang": "zh"},
    )
    assert zh.status_code == 400
    assert zh.json()["error"] == "enabled 必须是布尔值"
    en = client.post(
        "/api/schedules",
        json={"profile": "myapp", "kind": "daily", "time": "09:30", "enabled": "true"},
        cookies={"asc_lang": "en"},
    )
    assert en.status_code == 400
    assert en.json()["error"] == "enabled must be a boolean"
    assert not path.exists()


def test_unknown_id_is_404(scheduled):
    client, _, _, _ = scheduled
    deleted = client.delete("/api/schedules/ffffffff")
    ran = client.post("/api/schedules/ffffffff/run")
    assert deleted.status_code == 404
    assert ran.status_code == 404
    assert "error" in deleted.json()
    assert "detail" not in deleted.json()


def test_lock_timeout_is_409(scheduled, monkeypatch: pytest.MonkeyPatch):
    client, _, _, _ = scheduled

    def boom(*args, **kwargs):
        raise ScheduleLockTimeout()

    monkeypatch.setattr("asc.schedule.schedule_lock", boom)
    response = client.post(
        "/api/schedules",
        json={"profile": "myapp", "kind": "daily", "time": "09:30"},
    )
    assert response.status_code == 409
    assert "error" in response.json()


def test_corrupt_file_returns_400_without_rewrite(scheduled):
    client, path, _, _ = scheduled
    path.write_text('tasks = "no"\n', encoding="utf-8")
    before = path.read_bytes()
    response = client.get("/api/schedules", cookies={"asc_lang": "zh"})
    assert response.status_code == 400
    assert "error" in response.json()
    assert path.read_bytes() == before


def test_run_now_checks_review_and_sends_webhook_without_moving_next(
    scheduled, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    client, path, backend, _ = scheduled
    created = client.post(
        "/api/schedules",
        json={"profile": "myapp", "kind": "daily", "time": "09:30", "enabled": False},
    )
    assert created.status_code == 200
    task_id = created.json()["id"]
    before = load_tasks(path)[0].next_run_at
    bootstraps = list(backend.bootstraps)
    key = tmp_path / "AuthKey.p8"
    key.write_bytes(b"not-a-real-key")
    hook = tmp_path / "webhook.toml"
    hook.write_text(
        "\n".join([
            "enabled = true",
            "[providers.feishu]",
            "enabled = true",
            'url = "https://example.com/hook"',
        ]),
        encoding="utf-8",
    )
    monkeypatch.setenv("ASC_WEBHOOK_CONFIG_PATH", str(hook))

    class FakeConnect:
        def __init__(self, issuer_id, key_id, key_file):
            self.args = (issuer_id, key_id, key_file)

        def _get_paginated_data(self, api_path, **params):
            calls.append((api_path, params))
            return [{
                "id": "v1",
                "attributes": {"appStoreState": "IN_REVIEW", "versionString": "1.2.3"},
            }]

    calls = []
    sent = []

    def lookup(name):
        return {
            "issuer_id": "issuer",
            "key_id": "KEYID",
            "key_file": str(key),
            "app_id": "123",
        }

    def fake_send(provider, config, text):
        sent.append((provider, text))
        return {"provider": provider, "ok": True}

    def forbid_subprocess(*args, **kwargs):
        raise AssertionError(args)

    monkeypatch.setattr("asc.schedule.query_review", real_query_review)
    monkeypatch.setattr("asc.schedule.default_profile_lookup", lookup)
    monkeypatch.setattr("asc.schedule._default_guard", lambda profile, creds: None)
    monkeypatch.setattr("asc.api.AppStoreConnectAPI", FakeConnect)
    monkeypatch.setattr("asc.web.webhook_clients.send_provider", fake_send)
    monkeypatch.setattr("asc.schedule.subprocess.run", forbid_subprocess)

    ran = client.post(f"/api/schedules/{task_id}/run")

    assert ran.status_code == 200
    body = ran.json()
    assert body["last_result"] == "1.2.3 审核中"
    assert body["last_error"] == ""
    assert body["enabled"] is False
    assert body["next_run_at"] == before
    saved = load_tasks(path)[0]
    assert saved.next_run_at == before
    assert saved.last_result == "1.2.3 审核中"
    assert saved.last_error == ""
    assert calls == [("/v1/apps/123/appStoreVersions", {"filter[platform]": "IOS"})]
    assert sent and sent[0][0] == "feishu"
    assert "1.2.3" in sent[0][1]
    assert backend.bootstraps == bootstraps


def test_run_failure_returns_200_without_moving_next(scheduled):
    client, path, _, _ = scheduled
    created = client.post("/api/schedules", json={"profile": "myapp", "kind": "daily", "time": "09:30"})
    assert created.status_code == 200
    task_id = created.json()["id"]
    before = load_tasks(path)[0].next_run_at
    ran = client.post(f"/api/schedules/{task_id}/run")
    assert ran.status_code == 200
    body = ran.json()
    assert body["last_error"]
    assert body["next_run_at"] == before
    assert load_tasks(path)[0].next_run_at == before


def test_schedules_page_is_wired():
    import json

    root = Path(__file__).resolve().parents[1]
    router = (root / "frontend/src/router/index.ts").read_text(encoding="utf-8")
    sidebar = (root / "frontend/src/components/AppSidebar.vue").read_text(encoding="utf-8")
    topbar = (root / "frontend/src/components/AppTopbar.vue").read_text(encoding="utf-8")
    view = (root / "frontend/src/views/SchedulesView.vue").read_text(encoding="utf-8")
    zh = json.loads((root / "src/asc/web/locales/zh.json").read_text(encoding="utf-8"))
    en = json.loads((root / "src/asc/web/locales/en.json").read_text(encoding="utf-8"))

    assert 'path: "/schedules"' in router
    assert "SchedulesView" in router
    assert "SYSTEM_PAGES" in router
    assert '"schedules"' not in router.split("SYSTEM_PAGES", 1)[1].split(";", 1)[0]
    profiles = sidebar.split('to: "/profiles"', 1)[1]
    assert profiles.index('to: "/schedules"') < profiles.index('to: "/guard"')
    assert 'labelKey: "nav.schedules"' in sidebar
    assert 'icon: "notes"' in sidebar
    assert 'p === "/schedules"' in topbar
    assert "nav.schedules" in topbar
    assert zh["nav.schedules"] == "定时任务"
    assert en["nav.schedules"] == "Schedules"
    assert zh["schedules.run"] == "立即执行"
    assert en["schedules.run"] == "Run now"
    assert zh["schedules.watch_app_store"] == "App Store 版本审核"
    assert en["schedules.watch_app_store"] == "App Store version review"
    assert zh["schedules.watch_testflight"] == "TF 外部组版本审核"
    assert en["schedules.watch_testflight"] == "TF external Beta Review"
    assert 'v-model="form.watch"' in view
    assert 'value="app_store"' in view
    assert 'value="testflight"' in view
    assert "isRunning(row.id)" in view
    assert ':disabled="isRunning(row.id)"' in view
    assert ':disabled="!row.enabled"' not in view
    assert "runSummary" in view
    assert [key for key in zh if key.startswith("schedules.")] == [
        key for key in en if key.startswith("schedules.")
    ]
    assert "/api/schedules" in view
    assert "/api/schedules/timezones" in view
    assert "useProfile" in view
    assert "function profileForCreate" in view
    assert "profileNames.value.includes(current)" in view
    assert "form.profile = profileForCreate()" in view
    assert 'snapshot.value?.current_profile || ""' in view
    assert "filterable" in view
    assert "schedules.timezone_auto" in view
    assert "body.timezone = form.timezone" in view
    assert "t-popconfirm" in view
    assert "function truncateTime" in view
    assert "slice(0, 5)" in view
    assert "new Date" not in view
    assert "next_run_at" not in view.split("JSON.stringify", 1)[-1]
    assert "notify_kinds" not in view
    assert "notify_statuses" not in view


def test_create_and_update_watch_testflight(scheduled):
    client, path, _, _ = scheduled
    created = client.post(
        "/api/schedules",
        json={"profile": "myapp", "kind": "daily", "time": "09:30", "watch": "testflight"},
    )
    assert created.status_code == 200, created.text
    assert created.json()["watch"] == "testflight"
    assert load_tasks(path)[0].watch == "testflight"
    omitted = client.post("/api/schedules", json={"profile": "myapp", "kind": "daily", "time": "10:30"})
    assert omitted.status_code == 200
    assert omitted.json()["watch"] == "app_store"
    updated = client.put(
        f"/api/schedules/{created.json()['id']}",
        json={
            "profile": "myapp",
            "kind": "daily",
            "time": "09:30",
            "enabled": True,
            "watch": "app_store",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["watch"] == "app_store"
    zh = client.post(
        "/api/schedules",
        json={"profile": "myapp", "kind": "daily", "time": "11:30", "watch": "store"},
        cookies={"asc_lang": "zh"},
    )
    assert zh.status_code == 400
    assert zh.json() == {"error": "监听类型必须是 app_store 或 testflight"}
    en = client.post(
        "/api/schedules",
        json={"profile": "myapp", "kind": "daily", "time": "11:30", "watch": "store"},
        cookies={"asc_lang": "en"},
    )
    assert en.status_code == 400
    assert en.json() == {"error": "Watch type must be app_store or testflight"}


def test_run_testflight_watch_queries_builds_not_versions(
    scheduled, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    client, path, _, _ = scheduled
    created = client.post(
        "/api/schedules",
        json={"profile": "myapp", "kind": "daily", "time": "09:30", "watch": "testflight"},
    )
    assert created.status_code == 200
    task_id = created.json()["id"]
    key = tmp_path / "AuthKey.p8"
    key.write_bytes(b"not-a-real-key")

    class FakeConnect:
        def __init__(self, issuer_id, key_id, key_file):
            self.args = (issuer_id, key_id, key_file)

        def list_builds(self, app_id, **params):
            calls.append(("list_builds", app_id, params))
            return {
                "data": [
                    {
                        "type": "builds",
                        "id": "b1",
                        "attributes": {"version": "123", "expired": False},
                        "relationships": {
                            "betaAppReviewSubmission": {
                                "data": {"type": "betaAppReviewSubmissions", "id": "s1"}
                            },
                            "buildBetaDetail": {
                                "data": {"type": "buildBetaDetails", "id": "d1"}
                            },
                            "betaGroups": {
                                "data": [{"type": "betaGroups", "id": "g1"}]
                            },
                        },
                    }
                ],
                "included": [
                    {
                        "type": "betaAppReviewSubmissions",
                        "id": "s1",
                        "attributes": {"betaReviewState": "WAITING_FOR_REVIEW"},
                    },
                    {
                        "type": "buildBetaDetails",
                        "id": "d1",
                        "attributes": {"externalBuildState": "WAITING_FOR_BETA_REVIEW"},
                    },
                    {
                        "type": "betaGroups",
                        "id": "g1",
                        "attributes": {"name": "External Testers", "isInternalGroup": False},
                    },
                ],
            }

        def list_beta_groups(self, app_id):
            raise AssertionError("groups included")

        def _get_paginated_data(self, api_path, **params):
            raise AssertionError(api_path)

    calls = []

    def lookup(name):
        return {
            "issuer_id": "issuer",
            "key_id": "KEYID",
            "key_file": str(key),
            "app_id": "123",
        }

    monkeypatch.setattr("asc.schedule.query_review", real_query_review)
    monkeypatch.setattr("asc.schedule.default_profile_lookup", lookup)
    monkeypatch.setattr("asc.schedule._default_guard", lambda profile, creds: None)
    monkeypatch.setattr("asc.api.AppStoreConnectAPI", FakeConnect)
    monkeypatch.setattr(
        "asc.schedule._default_send",
        lambda text: type("S", (), {"config_invalid": False, "failures": [], "attempted": False})(),
    )

    from asc.schedule import SendOutcome

    monkeypatch.setattr(
        "asc.schedule.send_channels",
        lambda text, sender=None: SendOutcome(False, [], False),
    )

    ran = client.post(f"/api/schedules/{task_id}/run")
    assert ran.status_code == 200, ran.text
    body = ran.json()
    assert body["watch"] == "testflight"
    assert body["last_result"].startswith("TF 123")
    assert body["last_error"] == ""
    assert calls and calls[0][0] == "list_builds"


def test_web_install_uses_sibling_asc_for_module_invocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from asc.web import routes_schedule

    bindir = tmp_path / "bin"
    bindir.mkdir()
    python = bindir / "python"
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    asc = bindir / "asc"
    asc.write_text("#!/bin/sh\n", encoding="utf-8")
    asc.chmod(0o755)
    module = tmp_path / "asc" / "__main__.py"
    module.parent.mkdir()
    module.write_text("print('module')\n", encoding="utf-8")
    empty = tmp_path / "empty-path"
    empty.mkdir()
    monkeypatch.setattr(sys, "executable", str(python))
    monkeypatch.setattr(sys, "argv", [str(module), "web"])
    monkeypatch.setenv("PATH", str(empty))
    backend = FakeHeartbeat()
    monkeypatch.setattr(routes_schedule, "heartbeat_backend", lambda: backend)
    client = TestClient(create_app())

    response = client.post("/api/schedules/heartbeat/install")

    assert response.status_code == 200
    assert response.json()["heartbeat"] == {"installed": True, "path": str(asc.resolve())}
    program = plistlib.loads(backend.plist)["ProgramArguments"]
    assert program == [str(asc.resolve()), "schedule", "tick"]
