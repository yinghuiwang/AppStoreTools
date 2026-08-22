"""Contract tests for listing / IAP agent workflows (no live LLM).

These lock the skill-adapted rules into CI:
- system prompt + knowledge notes + seed prompts
- scripted turns that call get_knowledge and propose_fix

They do not assert that a vendor model will follow the workflow. That needs an
opt-in live eval (ASC_TEST_LIVE=1 + real API key), which is out of default CI.
"""
from __future__ import annotations

import json

from asc.web.agent import WebAgent, _system_prompt
from asc.web.agent_knowledge import get_topic, search_notes
from asc.web.agent_store import AgentStore
from asc.web.i18n import t
from asc.web.tasks import TaskStore
from tests.test_web_agent import ScriptedLLM


def _run_turn(tmp_path, llm, *, message: str, replay: dict | None = None, kind: str = "metadata"):
    tasks = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    task_id = tasks.create(kind, profile="myapp", replay=replay or {})
    agent = WebAgent(agent_store=agents, task_store=tasks, project_root=tmp_path)
    events = list(
        agent.run_turn(
            session_id=None,
            task_id=task_id,
            message=message,
            auto_analyze=False,
            lang="zh",
            llm_client=llm,
        )
    )
    return events, llm, tasks, agents, task_id


def test_listing_and_iap_contracts_are_searchable():
    listing = get_topic("listing")
    iap = get_topic("iap")
    assert listing["ok"] and iap["ok"]
    assert listing.get("truncated") is not True
    assert iap.get("truncated") is not True
    assert "en-US" in listing["content"] and "zh-Hans" in listing["content"]
    assert "csv_set_fields" in listing["content"]
    assert "legal block" in listing["content"]
    assert "groupLevel" in iap["content"]
    assert "one category per message" in iap["content"]
    assert "infer_iap_products.rb" in iap["content"]

    prompt = _system_prompt("zh")
    assert "appstore-listing" in prompt
    assert "iap-packages" in prompt
    assert "en-US and zh-Hans" in prompt

    assert "en-US" in t("listing.agent_seed_create", lang="zh")
    assert "zh-Hans" in t("listing.agent_seed_create", lang="zh")
    assert "10 个选项" in t("iap.agent_seed_create", lang="zh")
    assert search_notes("appstore-listing")["hits"][0]["topic"] == "listing"
    assert any(hit["topic"] == "iap" for hit in search_notes("groupLevel")["hits"])


def test_scripted_listing_turn_loads_workflow_and_drafts_pilot_locales(tmp_path):
    csv_path = tmp_path / "data" / "appstore_info.csv"
    csv_path.parent.mkdir()
    csv_path.write_text("locale,name,subtitle,keywords,description\n", encoding="utf-8")
    before = csv_path.read_bytes()
    seed = t("listing.agent_seed_create", lang="zh")
    propose = {
        "summary": "pilot en-US + zh-Hans only",
        "mutations": [
            {
                "op": "csv_set_fields",
                "path": str(csv_path),
                "locale": locale,
                "fields": {"name": f"Demo: {locale}", "subtitle": "Unique benefit"},
            }
            for locale in ("en-US", "zh-Hans")
        ],
        "manual_steps": ["Wait for user confirmation before other locales"],
    }
    llm = ScriptedLLM(
        [
            [
                {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "k1",
                            "function": {
                                "name": "get_knowledge",
                                "arguments": '{"topic":"listing"}',
                            },
                        }
                    ]
                },
                {"finish_reason": "tool_calls"},
            ],
            [
                {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "p1",
                            "function": {
                                "name": "propose_fix",
                                "arguments": json.dumps(propose),
                            },
                        }
                    ]
                },
                {"finish_reason": "tool_calls"},
            ],
            [{"content": "先确认 en-US / zh-Hans，再写其他语言。", "finish_reason": "stop"}],
        ]
    )
    events, llm, tasks, agents, _task_id = _run_turn(
        tmp_path,
        llm,
        message=seed,
        replay={"kind": "metadata", "profile": "myapp", "params": {"csv_path": str(csv_path)}},
    )
    names = [name for name, _ in events]
    assert names[0] == "session"
    assert names.count("tool_start") == 2
    assert names[-1] == "done"
    system = llm.messages_seen[0][0]["content"]
    assert "appstore-listing" in system
    assert seed[:12] in json.dumps(llm.messages_seen[0], ensure_ascii=False)

    session_id = json.loads(events[0][1])["session_id"]
    tool_msgs = [row for row in agents.list_messages(session_id, limit=50) if row["role"] == "tool"]
    listing_note = next(
        row["content"]
        for row in tool_msgs
        if "appstore-listing" in row["content"] or '"topic": "listing"' in row["content"]
    )
    assert "27" in listing_note
    assert "legal block" in listing_note
    assert csv_path.read_bytes() == before
    plans = agents.list_plans(session_id)
    assert plans and plans[0]["status"] in {"draft", "pending"}
    locales = {item.get("locale") for item in propose["mutations"]}
    assert locales == {"en-US", "zh-Hans"}
    tasks.close()
    agents.close()


def test_scripted_iap_turn_loads_workflow_without_writing_json(tmp_path):
    iap_path = tmp_path / "data" / "iap_packages.json"
    iap_path.parent.mkdir()
    original = {
        "items": [],
        "subscriptionGroups": [
            {
                "referenceName": "Membership",
                "localizations": {"en-US": {"name": "Demo Pro"}},
                "subscriptions": [],
            }
        ],
    }
    iap_path.write_text(json.dumps(original), encoding="utf-8")
    seed = t("iap.agent_seed_create", lang="zh")
    propose = {
        "summary": "draft after groupLevel confirmation",
        "mutations": [
            {
                "op": "json_patch",
                "path": str(iap_path),
                "patch": [
                    {
                        "op": "replace",
                        "path": "/subscriptionGroups/0/localizations/en-US/name",
                        "value": "Demo Pro",
                    }
                ],
            }
        ],
        "manual_steps": ["Confirm groupLevel", "Pick localization option 1-10"],
    }
    llm = ScriptedLLM(
        [
            [
                {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "k1",
                            "function": {
                                "name": "get_knowledge",
                                "arguments": '{"topic":"iap"}',
                            },
                        }
                    ]
                },
                {"finish_reason": "tool_calls"},
            ],
            [
                {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "p1",
                            "function": {
                                "name": "propose_fix",
                                "arguments": json.dumps(propose),
                            },
                        }
                    ]
                },
                {"finish_reason": "tool_calls"},
            ],
            [{"content": "请先确认 groupLevel，再选订阅组文案。", "finish_reason": "stop"}],
        ]
    )
    events, llm, tasks, agents, _task_id = _run_turn(
        tmp_path,
        llm,
        message=seed,
        kind="iap",
        replay={"kind": "iap", "profile": "myapp", "params": {"iap_file": str(iap_path)}},
    )
    assert events[-1][0] == "done"
    assert "iap-packages" in llm.messages_seen[0][0]["content"]
    assert "groupLevel" in seed
    session_id = agents.list_sessions()[0]["id"]
    tool_blob = "\n".join(
        row["content"] for row in agents.list_messages(session_id, limit=50) if row["role"] == "tool"
    )
    assert "one category per message" in tool_blob
    assert "groupLevel" in tool_blob
    assert json.loads(iap_path.read_text(encoding="utf-8")) == original
    tasks.close()
    agents.close()
