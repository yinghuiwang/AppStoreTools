from __future__ import annotations

from asc.web.agent_redact import redact_obj, redact_text


def test_redact_text_strips_pem_p8_and_key_ids():
    raw = (
        "key_file=/Users/me/AuthKey_ABC123.p8 "
        "issuer_id=11223344-aaaa-bbbb-cccc-ddddeeeeffff "
        "key_id=AB12CD34 "
        "api_key=sk-secret "
        "-----BEGIN PRIVATE KEY-----\nMIIHideMe\n-----END PRIVATE KEY-----"
    )
    out = redact_text(raw)
    assert "MIIHideMe" not in out
    assert "sk-secret" not in out
    assert "AuthKey_ABC123.p8" not in out or ".p8" not in out
    assert "BEGIN PRIVATE KEY" not in out
    assert "11223344-aaaa-bbbb-cccc-ddddeeeeffff" not in out
    assert "AB12CD34" not in out


def test_redact_obj_walks_nested_and_caps():
    payload = {"result": {"error": "Bearer tok_live_abc failed"}, "nested": ["api_key=xyz"]}
    out = redact_obj(payload, max_chars=4096)
    blob = str(out)
    assert "tok_live_abc" not in blob
    assert "xyz" not in blob
