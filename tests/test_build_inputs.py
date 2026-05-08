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
