import plistlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from asc.commands.build_inputs import (
    BuildInputsCLI,
    ProfileInfo,
    ResolvedInputs,
    parse_mobileprovision,
)


def test_build_inputs_cli_defaults_to_none():
    cli = BuildInputsCLI()
    assert cli.project is None
    assert cli.scheme is None
    assert cli.signing is None
    assert cli.profile is None
    assert cli.certificate is None
    assert cli.destination is None


def test_resolved_inputs_required_fields():
    r = ResolvedInputs(
        project_path="/tmp/x.xcodeproj",
        project_kind="project",
        scheme="MyApp",
        bundle_id="com.example.app",
        signing="auto",
        certificate=None,
        profile=None,
        destination="appstore",
    )
    assert r.scheme == "MyApp"
    assert r.certificate is None


def _make_profile(tmp_path, *, bundle_id="com.example.app", expired=False, cert_sha1="ABC123"):
    plist = {
        "UUID": "11111111-2222-3333-4444-555555555555",
        "Name": "Test Profile",
        "TeamIdentifier": ["TEAMID"],
        "ExpirationDate": datetime.now(timezone.utc) + (timedelta(days=-1) if expired else timedelta(days=365)),
        "Entitlements": {"application-identifier": f"TEAMID.{bundle_id}"},
        "DeveloperCertificates": [b"<fake-cert-bytes>"],
    }
    p = tmp_path / "test.mobileprovision"
    p.write_bytes(plistlib.dumps(plist))
    return p, cert_sha1


def test_parse_mobileprovision_extracts_fields(tmp_path, monkeypatch):
    profile_path, cert_sha1 = _make_profile(tmp_path)

    def fake_decode(path):
        return plistlib.loads(Path(path).read_bytes())

    monkeypatch.setattr("asc.commands.build_inputs._decode_profile_plist", fake_decode)
    monkeypatch.setattr("asc.commands.build_inputs._cert_sha1", lambda b: cert_sha1)

    info = parse_mobileprovision(profile_path)
    assert isinstance(info, ProfileInfo)
    assert info.bundle_id == "com.example.app"
    assert info.uuid == "11111111-2222-3333-4444-555555555555"
    assert info.team_id == "TEAMID"
    assert info.cert_sha1s == [cert_sha1]
    assert info.is_expired is False


def test_parse_mobileprovision_detects_expired(tmp_path, monkeypatch):
    profile_path, _ = _make_profile(tmp_path, expired=True)
    monkeypatch.setattr("asc.commands.build_inputs._decode_profile_plist",
                        lambda path: plistlib.loads(Path(path).read_bytes()))
    monkeypatch.setattr("asc.commands.build_inputs._cert_sha1", lambda b: "X")
    info = parse_mobileprovision(profile_path)
    assert info.is_expired is True


def test_parse_mobileprovision_raises_when_expiration_missing(tmp_path, monkeypatch):
    import pytest
    p = tmp_path / "bad.mobileprovision"
    p.write_bytes(b"")
    monkeypatch.setattr(
        "asc.commands.build_inputs._decode_profile_plist",
        lambda _: {"UUID": "U", "Name": "N", "TeamIdentifier": ["T"],
                   "Entitlements": {"application-identifier": "T.com.x"},
                   "DeveloperCertificates": []},
    )
    with pytest.raises(RuntimeError, match="ExpirationDate"):
        parse_mobileprovision(p)


from asc.commands.build_inputs import scan_profiles


def test_scan_profiles_dedupes_by_uuid(tmp_path, monkeypatch):
    new_dir = tmp_path / "new"
    old_dir = tmp_path / "old"
    new_dir.mkdir(); old_dir.mkdir()

    same_uuid = "AAAA"
    import datetime as _dt

    def info_for(path, name):
        return ProfileInfo(
            path=str(path), uuid=same_uuid, name=name, team_id="T",
            bundle_id="com.x", expiration=_dt.datetime.now(),
            cert_sha1s=[],
        )

    new_file = new_dir / "a.mobileprovision"
    old_file = old_dir / "a.mobileprovision"
    new_file.write_bytes(b""); old_file.write_bytes(b"")

    fake_parsed = {
        str(new_file): info_for(new_file, "NEW"),
        str(old_file): info_for(old_file, "OLD"),
    }
    monkeypatch.setattr(
        "asc.commands.build_inputs.parse_mobileprovision",
        lambda p: fake_parsed[str(p)],
    )

    result = scan_profiles(dirs=[new_dir, old_dir])
    assert len(result) == 1
    assert result[0].name == "NEW"


def test_scan_profiles_skips_unreadable(tmp_path, monkeypatch):
    d = tmp_path / "p"
    d.mkdir()
    (d / "broken.mobileprovision").write_bytes(b"")

    def boom(_):
        raise RuntimeError("decode failed")

    monkeypatch.setattr("asc.commands.build_inputs.parse_mobileprovision", boom)
    result = scan_profiles(dirs=[d])
    assert result == []


def test_scan_profiles_skips_missing_dirs(tmp_path, monkeypatch):
    existing = tmp_path / "exists"
    existing.mkdir()
    missing = tmp_path / "never-created"
    result = scan_profiles(dirs=[missing, existing])
    assert result == []


from asc.commands.build_inputs import detect_profiles


def _info(name, bundle, expired, sha1s):
    exp = datetime.now(timezone.utc) + (timedelta(days=-1) if expired else timedelta(days=30))
    return ProfileInfo(path=f"/p/{name}", uuid=name, name=name, team_id="T",
                       bundle_id=bundle, expiration=exp, cert_sha1s=sha1s)


def test_detect_profiles_filters_bundle_expiry_cert(monkeypatch):
    pool = [
        _info("ok",       "com.a", expired=False, sha1s=["AAA", "BBB"]),
        _info("wrong-bid","com.b", expired=False, sha1s=["AAA"]),
        _info("expired",  "com.a", expired=True,  sha1s=["AAA"]),
        _info("no-cert",  "com.a", expired=False, sha1s=["ZZZ"]),
    ]
    monkeypatch.setattr("asc.commands.build_inputs.scan_profiles", lambda: pool)

    result = detect_profiles(bundle_id="com.a", cert_sha1="AAA")
    assert [p.name for p in result] == ["ok"]


def test_detect_profiles_no_cert_filter_when_sha1_none(monkeypatch):
    pool = [_info("a", "com.a", False, ["X"]), _info("b", "com.a", False, ["Y"])]
    monkeypatch.setattr("asc.commands.build_inputs.scan_profiles", lambda: pool)
    result = detect_profiles(bundle_id="com.a", cert_sha1=None)
    assert {p.name for p in result} == {"a", "b"}


def test_detect_profiles_case_insensitive_sha1(monkeypatch):
    pool = [_info("ok", "com.a", False, ["aabbcc"])]
    monkeypatch.setattr("asc.commands.build_inputs.scan_profiles", lambda: pool)
    result = detect_profiles(bundle_id="com.a", cert_sha1="AABBCC")
    assert len(result) == 1


from asc.commands.build_inputs import detect_certificates, Certificate


SECURITY_OUTPUT = """\
Policy: Code Signing
  Matching identities
  1) A6D6D6EE49D04E2EE9F8E7FF6EED2A461ACE0BCA "Apple Distribution: yiqi bai (2T6LGHS8XQ)"
  2) DEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEF "Apple Development: dev (XYZ)"
  3) CAFECAFECAFECAFECAFECAFECAFECAFECAFECAFE "iPhone Distribution: ACME Inc (ABCDEF1234)"
     3 identities found
"""


def test_detect_certificates_keeps_distribution_only(monkeypatch):
    class FakeRun:
        returncode = 0
        stdout = SECURITY_OUTPUT
        stderr = ""

    monkeypatch.setattr(
        "asc.commands.build_inputs.subprocess.run",
        lambda *a, **kw: FakeRun(),
    )
    certs = detect_certificates()
    names = [c.name for c in certs]
    assert names == [
        "Apple Distribution: yiqi bai (2T6LGHS8XQ)",
        "iPhone Distribution: ACME Inc (ABCDEF1234)",
    ]
    assert certs[0].sha1 == "A6D6D6EE49D04E2EE9F8E7FF6EED2A461ACE0BCA"


def test_detect_certificates_returns_empty_when_security_fails(monkeypatch):
    class FakeRun:
        returncode = 1
        stdout = ""
        stderr = "err"

    monkeypatch.setattr(
        "asc.commands.build_inputs.subprocess.run",
        lambda *a, **kw: FakeRun(),
    )
    assert detect_certificates() == []


from asc.commands.build_inputs import detect_bundle_id


XCODEBUILD_OUTPUT = """\
Build settings for action build and target PokeVid:
    PRODUCT_BUNDLE_IDENTIFIER = com.baiyiqi.pokevid
    PRODUCT_NAME = PokeVid
"""


def test_detect_bundle_id_parses_product_bundle_identifier(monkeypatch):
    class FakeRun:
        returncode = 0
        stdout = XCODEBUILD_OUTPUT
        stderr = ""

    monkeypatch.setattr(
        "asc.commands.build_inputs.subprocess.run",
        lambda *a, **kw: FakeRun(),
    )
    assert detect_bundle_id("/x.xcodeproj", "project", "PokeVid") == "com.baiyiqi.pokevid"


def test_detect_bundle_id_workspace_passes_workspace_flag(monkeypatch):
    captured = {}

    class FakeRun:
        returncode = 0
        stdout = XCODEBUILD_OUTPUT
        stderr = ""

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return FakeRun()

    monkeypatch.setattr("asc.commands.build_inputs.subprocess.run", fake_run)
    detect_bundle_id("/x.xcworkspace", "workspace", "X")
    assert "-workspace" in captured["cmd"]
    assert "-project" not in captured["cmd"]


def test_detect_bundle_id_returns_none_on_failure(monkeypatch):
    class FakeRun:
        returncode = 1
        stdout = ""
        stderr = "error"

    monkeypatch.setattr(
        "asc.commands.build_inputs.subprocess.run",
        lambda *a, **kw: FakeRun(),
    )
    assert detect_bundle_id("/x.xcodeproj", "project", "X") is None


def test_detect_bundle_id_returns_none_when_setting_absent(monkeypatch):
    class FakeRun:
        returncode = 0
        stdout = "Build settings...\n    OTHER_SETTING = foo\n"
        stderr = ""

    monkeypatch.setattr(
        "asc.commands.build_inputs.subprocess.run",
        lambda *a, **kw: FakeRun(),
    )
    assert detect_bundle_id("/x.xcodeproj", "project", "X") is None


import os
from asc.config import Config


def test_update_local_build_section_creates_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = Config()
    cfg.update_local_build_section({
        "project": "/abs/MyApp.xcodeproj",
        "scheme": "MyApp",
        "signing": "manual",
    })

    text = (tmp_path / ".asc" / "config.toml").read_text()
    assert "[build]" in text
    assert 'project = "/abs/MyApp.xcodeproj"' in text
    assert 'scheme = "MyApp"' in text
    assert 'signing = "manual"' in text


def test_update_local_build_section_merges_with_existing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    asc_dir = tmp_path / ".asc"
    asc_dir.mkdir()
    (asc_dir / "config.toml").write_text(
        '[credentials]\nissuer_id = "x"\n\n[build]\nproject = "old.xcodeproj"\n'
    )

    cfg = Config()
    cfg.update_local_build_section({"scheme": "New"})

    text = (asc_dir / "config.toml").read_text()
    assert 'issuer_id = "x"' in text
    assert 'project = "old.xcodeproj"' in text
    assert 'scheme = "New"' in text


def test_update_local_build_section_skips_none_values(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = Config()
    cfg.update_local_build_section({"scheme": "X", "profile": None})
    text = (tmp_path / ".asc" / "config.toml").read_text()
    assert 'scheme = "X"' in text
    assert "profile" not in text


def test_update_local_build_section_escapes_quotes_and_backslashes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = Config()
    cfg.update_local_build_section({"certificate": 'Apple "Distribution"', "profile": "C:\\path"})
    text = (tmp_path / ".asc" / "config.toml").read_text()
    # Re-parse and verify roundtrip integrity
    cfg2 = Config()
    assert cfg2.get("certificate", section="build") == 'Apple "Distribution"'
    assert cfg2.get("profile", section="build") == "C:\\path"


def test_config_build_properties_read_local_toml(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    asc_dir = tmp_path / ".asc"
    asc_dir.mkdir()
    (asc_dir / "config.toml").write_text(
        '[build]\n'
        'bundle_id = "com.x.y"\n'
        'certificate = "Apple Distribution: x"\n'
        'profile = "/p/abc.mobileprovision"\n'
        'destination = "appstore"\n'
    )
    cfg = Config()
    assert cfg.build_bundle_id == "com.x.y"
    assert cfg.build_certificate == "Apple Distribution: x"
    assert cfg.build_profile == "/p/abc.mobileprovision"
    assert cfg.build_destination == "appstore"


def test_config_build_destination_falls_back_to_global(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    profiles_dir = home / ".config" / "asc" / "profiles"
    profiles_dir.mkdir(parents=True)
    (profiles_dir / "myapp.toml").write_text('[build]\ndestination = "testflight"\n')

    cfg = Config(app_name="myapp")
    assert cfg.build_destination == "testflight"


def test_config_build_properties_return_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = Config()
    assert cfg.build_bundle_id is None
    assert cfg.build_certificate is None
    assert cfg.build_profile is None
    assert cfg.build_destination is None


from asc.commands.build_inputs import validate_cache_entry


def test_validate_cache_entry_project_path(tmp_path):
    real = tmp_path / "x.xcodeproj"
    real.mkdir()
    assert validate_cache_entry("project", str(real)) is True
    assert validate_cache_entry("project", str(tmp_path / "missing")) is False


def test_validate_cache_entry_certificate(monkeypatch):
    monkeypatch.setattr(
        "asc.commands.build_inputs.detect_certificates",
        lambda: [Certificate(sha1="X", name="Apple Distribution: yiqi bai (T)")],
    )
    assert validate_cache_entry("certificate", "Apple Distribution: yiqi bai (T)") is True
    assert validate_cache_entry("certificate", "Apple Distribution: gone") is False


def test_validate_cache_entry_profile(tmp_path, monkeypatch):
    p = tmp_path / "ok.mobileprovision"
    p.write_bytes(b"")
    valid = ProfileInfo(
        path=str(p), uuid="U", name="N", team_id="T",
        bundle_id="b",
        expiration=datetime.now(timezone.utc) + timedelta(days=10),
        cert_sha1s=[],
    )
    monkeypatch.setattr("asc.commands.build_inputs.parse_mobileprovision", lambda _: valid)
    assert validate_cache_entry("profile", str(p)) is True
    assert validate_cache_entry("profile", str(tmp_path / "missing.mobileprovision")) is False


def test_validate_cache_entry_profile_expired(tmp_path, monkeypatch):
    p = tmp_path / "exp.mobileprovision"
    p.write_bytes(b"")
    expired = ProfileInfo(
        path=str(p), uuid="U", name="N", team_id="T",
        bundle_id="b",
        expiration=datetime.now(timezone.utc) - timedelta(days=1),
        cert_sha1s=[],
    )
    monkeypatch.setattr("asc.commands.build_inputs.parse_mobileprovision", lambda _: expired)
    assert validate_cache_entry("profile", str(p)) is False


def test_validate_cache_entry_unknown_field_passes_through():
    assert validate_cache_entry("scheme", "anything") is True
    assert validate_cache_entry("bundle_id", "com.x") is True


def test_validate_cache_entry_empty_value_false():
    assert validate_cache_entry("project", "") is False
    assert validate_cache_entry("certificate", "") is False


from asc.commands.build_inputs import _pick_one


def test_pick_one_zero_raises():
    with pytest.raises(RuntimeError, match="找不到"):
        _pick_one([], label="证书", interactive=True)


def test_pick_one_single_silent():
    result = _pick_one(["only"], label="证书", interactive=True)
    assert result == "only"


def test_pick_one_multi_non_interactive_raises():
    with pytest.raises(RuntimeError, match="多个"):
        _pick_one(["a", "b"], label="证书", interactive=False)


def test_pick_one_multi_interactive_prompts(monkeypatch):
    monkeypatch.setattr("typer.prompt", lambda *a, **kw: "2")
    result = _pick_one(["a", "b", "c"], label="证书", interactive=True)
    assert result == "b"


def test_pick_one_multi_interactive_uses_renderer(monkeypatch, capsys):
    monkeypatch.setattr("typer.prompt", lambda *a, **kw: "1")
    items = [{"name": "X"}, {"name": "Y"}]
    result = _pick_one(items, label="X", interactive=True, render=lambda d: d["name"])
    assert result == items[0]
    captured = capsys.readouterr()
    assert "X" in captured.out and "Y" in captured.out
