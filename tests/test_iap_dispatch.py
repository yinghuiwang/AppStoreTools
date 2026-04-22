"""Entry dispatch tests for asc iap (items vs subscriptionGroups)."""
from __future__ import annotations

import json

from asc.commands.iap import _load_iap_config


def test_items_only_returns_empty_subs(tmp_path):
    f = tmp_path / "p.json"
    f.write_text(json.dumps({"items": [{"productId": "a"}]}))
    items, subs = _load_iap_config(str(f))
    assert items == [{"productId": "a"}]
    assert subs == []


def test_subs_only_returns_empty_items(tmp_path):
    f = tmp_path / "p.json"
    f.write_text(json.dumps({"subscriptionGroups": [{"referenceName": "Pro"}]}))
    items, subs = _load_iap_config(str(f))
    assert items == []
    assert subs == [{"referenceName": "Pro"}]


def test_top_level_array_is_items(tmp_path):
    f = tmp_path / "p.json"
    f.write_text(json.dumps([{"productId": "a"}]))
    items, subs = _load_iap_config(str(f))
    assert items == [{"productId": "a"}]
    assert subs == []


def test_mixed(tmp_path):
    f = tmp_path / "p.json"
    f.write_text(json.dumps({
        "items": [{"productId": "a"}],
        "subscriptionGroups": [{"referenceName": "Pro"}],
    }))
    items, subs = _load_iap_config(str(f))
    assert items == [{"productId": "a"}]
    assert subs == [{"referenceName": "Pro"}]


def test_empty_file_rejected(tmp_path):
    import pytest
    f = tmp_path / "p.json"
    f.write_text(json.dumps({}))
    with pytest.raises(ValueError, match="empty"):
        _load_iap_config(str(f))