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
