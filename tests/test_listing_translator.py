from __future__ import annotations

from asc.listing.translator import (
    ListingTranslator,
    _extract_fields,
    clip_description,
    clip_keywords,
    clip_name,
    clip_subtitle,
)


class FakeClient:
    def __init__(self, content: str) -> None:
        self.content = content
        self.messages = None
        self.temperature = None

    def chat(self, messages, temperature=0.3):
        self.messages = messages
        self.temperature = temperature
        return self.content


def test_clip_helpers_trim_and_honor_limits():
    assert clip_name("  Hello  ") == "Hello"
    assert len(clip_name("N" * 40)) == 30
    assert clip_subtitle("S" * 40) == "S" * 30
    assert clip_keywords("a,b," + "k" * 120).endswith("k") or "," in clip_keywords("a,b")
    clipped = clip_keywords("word," * 40)
    assert len(clipped) <= 100
    assert not clipped.endswith(",")
    assert len(clip_description("D" * 5000)) == 4000


def test_extract_fields_parses_json_and_plain_text():
    assert _extract_fields('{"name":"App","keywords":"a,b"}')["name"] == "App"
    assert _extract_fields("Plain title")["name"] == "Plain title"
    assert _extract_fields("") == {}


def test_translate_fields_clips_and_keeps_locale():
    client = FakeClient(
        '{"name":"' + ("N" * 40) + '","subtitle":"Sub","keywords":"a, b","description":"Desc"}'
    )
    out = ListingTranslator(client).translate_fields(
        source_locale="en-US",
        target_locale="zh-Hans",
        fields={"name": "Old", "subtitle": "", "keywords": "", "description": "Old desc"},
    )
    assert out["locale"] == "zh-Hans"
    assert out["name"] == "N" * 30
    assert out["subtitle"] == "Sub"
    assert out["keywords"] == "a, b"
    assert out["description"] == "Desc"
    assert client.messages[0]["role"] == "system"
    assert "zh-Hans" in client.messages[1]["content"]


def test_keywords_mode_only_returns_keywords():
    client = FakeClient('{"name":"App","keywords":"game,fun,play"}')
    out = ListingTranslator(client).translate_fields(
        source_locale="en-US",
        target_locale="ja",
        fields={"name": "App", "keywords": "old"},
        mode="keywords",
    )
    assert out == {"locale": "ja", "keywords": "game,fun,play"}
    assert "keyword" in client.messages[1]["content"].lower()
