"""Tests for the memory overhaul: episodic turns, scoped recall, maintenance."""

from datetime import datetime, timedelta

import pytest

from macbot.memory.database import AgentMemory
from macbot.memory.knowledge import KnowledgeMemory, _today
from macbot.memory.maintenance import _parse_insights, run_maintenance
from macbot.memory.tagging import score_domains, tag_domain
from macbot.providers.base import LLMResponse


# --------------------------------------------------------------------------- #
# Tagging
# --------------------------------------------------------------------------- #

def test_tag_domain_finances():
    assert tag_domain("help me pay this invoice via SEPA") == "finances"


def test_tag_domain_word_boundary_no_false_match():
    # "pay" must not match inside "paperless"; documents should win.
    assert tag_domain("tag this paperless document") == "documents"


def test_tag_domain_general_fallback():
    assert tag_domain("hello there") == "general"


def test_score_domains_multiple():
    scores = score_domains("email me the invoice")
    assert "mail" in scores and "finances" in scores


# --------------------------------------------------------------------------- #
# Episodic turns
# --------------------------------------------------------------------------- #

@pytest.fixture
def mem(tmp_path):
    return AgentMemory(db_path=tmp_path / "memory.db")


def test_record_and_get_turn(mem):
    tid = mem.record_turn(
        goal="pay the rent invoice",
        domain="finances",
        tools_used=["paperless_search", "generate_girocode"],
        outcome="success",
        summary="Created a GiroCode",
        model="chatgpt/gpt-5.5",
        tokens=1234,
    )
    assert tid > 0
    turns = mem.get_unconsolidated_turns()
    assert len(turns) == 1
    assert turns[0]["domain"] == "finances"
    assert turns[0]["tools_used"] == ["paperless_search", "generate_girocode"]


def test_mark_turns_consolidated(mem):
    tid = mem.record_turn(goal="x")
    assert mem.mark_turns_consolidated([tid]) == 1
    assert mem.get_unconsolidated_turns() == []


def test_clear_old_records_only_prunes_consolidated_turns(mem):
    import sqlite3

    # Insert an old turn directly so we control the timestamp.
    old_ts = (datetime.now() - timedelta(days=200)).strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(mem.db_path) as conn:
        conn.execute(
            "INSERT INTO turns (ts, goal, consolidated) VALUES (?, ?, 0)",
            (old_ts, "old unconsolidated"),
        )
        conn.execute(
            "INSERT INTO turns (ts, goal, consolidated) VALUES (?, ?, 1)",
            (old_ts, "old consolidated"),
        )
    mem.clear_old_records(days=90)
    remaining = mem.get_recent_turns(limit=10)
    goals = {t["goal"] for t in remaining}
    assert "old unconsolidated" in goals  # kept — not yet distilled
    assert "old consolidated" not in goals  # pruned


# --------------------------------------------------------------------------- #
# Knowledge: schema, backward compat, scoped recall
# --------------------------------------------------------------------------- #

@pytest.fixture
def know(tmp_path):
    return KnowledgeMemory(path=str(tmp_path / "memory.yaml"))


def test_legacy_items_load_with_defaults(tmp_path):
    path = tmp_path / "memory.yaml"
    path.write_text(
        "lessons_learned:\n- topic: old\n  lesson: legacy lesson\n"
        "user_preferences: []\nuser_facts: []\n"
    )
    k = KnowledgeMemory(path=str(path))
    item = k.get_all()["lessons_learned"][0]
    assert item["importance"] == 3
    assert item["domain"] == []
    assert item["source"] == "auto"
    assert item["created"]  # filled


def test_add_with_domain_and_importance(know):
    know.add_fact("Pays rent on the 1st", domain="finances", importance=4)
    item = know.get_all()["user_facts"][0]
    assert item["domain"] == ["finances"]
    assert item["importance"] == 4


def test_scoped_recall_prefers_matching_domain(know):
    know.add_fact("Pays rent on the 1st", domain="finances", importance=3)
    know.add_fact("Likes window seats on flights", domain="travel", importance=3)
    out = know.format_for_prompt(query="help me with my finances", top_k=1)
    assert "rent" in out
    assert "window seats" not in out


def test_user_preferences_always_injected(know):
    # A user preference in an unrelated domain still shows for any query.
    know.set_preference("communication", "be terse", domain="general", source="user")
    know.add_fact("noise", domain="coding", importance=1)
    out = know.format_for_prompt(query="book me a flight", top_k=1)
    assert "be terse" in out


def test_no_query_uses_legacy_tail(know):
    for i in range(5):
        know.add_fact(f"fact {i}", importance=2)
    out = know.format_for_prompt(max_items=2)
    assert "fact 4" in out and "fact 3" in out
    assert "fact 0" not in out


def test_search_marks_last_used(know):
    know.add_fact("Pays rent on the 1st", domain="finances")
    results = know.search("finances rent")
    assert results and results[0]["score"] > 0
    assert know.get_all()["user_facts"][0]["last_used"] == _today()


# --------------------------------------------------------------------------- #
# Maintenance helpers
# --------------------------------------------------------------------------- #

def _inject_fact(know, text, importance):
    """Append a fact directly, bypassing add_fact's write-time dedup."""
    data = know.get_all()
    data["user_facts"].append(know._fill_defaults({
        "fact": text, "importance": importance, "created": _today(), "updated": _today(),
    }))
    know.save()


def test_merge_similar_dedupes_facts(know):
    # add_fact dedupes at write time; merge_similar cleans up duplicates that
    # slipped in another way (legacy files, direct edits).
    _inject_fact(know, "Lives in Germany", 3)
    _inject_fact(know, "lives in germany.", 4)  # normalized duplicate
    removed = know.merge_similar()
    assert removed == 1
    facts = know.get_all()["user_facts"]
    assert len(facts) == 1
    assert facts[0]["importance"] == 4  # kept the higher-importance copy


def test_expire_stale_removes_old_low_importance_auto(know):
    know.add_fact("ephemeral note", importance=1, source="auto")
    item = know.get_all()["user_facts"][0]
    item["last_used"] = (datetime.now() - timedelta(days=200)).strftime("%Y-%m-%d")
    item["updated"] = item["last_used"]
    know.save()
    removed = know.expire_stale(max_age_days=90)
    assert removed == 1
    assert know.get_all()["user_facts"] == []


def test_expire_stale_keeps_user_and_important(know):
    know.set_preference("output", "terse", source="user")  # user → never expires
    know.add_fact("critical fact", importance=5, source="auto")  # high importance
    for section in ("user_preferences", "user_facts"):
        for it in know.get_all()[section]:
            it["last_used"] = (datetime.now() - timedelta(days=999)).strftime("%Y-%m-%d")
    know.save()
    assert know.expire_stale(max_age_days=90) == 0


def test_expire_respects_explicit_expiry(know):
    know.add_lesson("temp", "short lived", importance=5, ttl_days=-1)  # already expired
    # importance 5 would normally be kept, but an explicit past expiry wins.
    assert know.expire_stale() == 1


# --------------------------------------------------------------------------- #
# Maintenance end-to-end with a fake provider
# --------------------------------------------------------------------------- #

def test_parse_insights_strips_code_fences():
    text = '```json\n[{"kind":"fact","text":"x","domain":"general","importance":3}]\n```'
    out = _parse_insights(text)
    assert out == [{"kind": "fact", "text": "x", "domain": "general", "importance": 3}]


class _FakeProvider:
    def __init__(self, payload: str):
        self._payload = payload

    async def chat(self, messages, tools=None, system_prompt=None, stream_callback=None):
        return LLMResponse(content=self._payload)


class _FakeConfig:
    memory_retention_days = 90


@pytest.mark.asyncio
async def test_run_maintenance_distills_and_consolidates(tmp_path):
    mem = AgentMemory(db_path=tmp_path / "memory.db")
    know = KnowledgeMemory(path=str(tmp_path / "memory.yaml"))
    mem.record_turn(
        goal="pay the electricity invoice",
        domain="finances",
        tools_used=["generate_girocode"],
        outcome="success",
        summary="made a girocode",
    )
    provider = _FakeProvider(
        '[{"kind":"preference","key":"payments",'
        '"text":"Prefers GiroCode for invoices","domain":"finances","importance":4}]'
    )
    report = await run_maintenance(
        config=_FakeConfig(), provider=provider, memory=mem, knowledge=know,
    )
    assert report["turns_seen"] == 1
    assert report["distilled"] == 1
    assert mem.get_unconsolidated_turns() == []  # marked consolidated
    prefs = know.get_all()["user_preferences"]
    assert prefs[0]["category"] == "payments"
    assert prefs[0]["domain"] == ["finances"]


@pytest.mark.asyncio
async def test_run_maintenance_tidies_even_without_turns(tmp_path):
    mem = AgentMemory(db_path=tmp_path / "memory.db")
    know = KnowledgeMemory(path=str(tmp_path / "memory.yaml"))
    know.add_fact("Lives in Germany", importance=3)
    # Inject a raw duplicate that bypasses add_fact's write-time dedup.
    data = know.get_all()
    data["user_facts"].append(know._fill_defaults({
        "fact": "lives in germany", "importance": 3, "created": _today(), "updated": _today(),
    }))
    know.save()
    report = await run_maintenance(
        config=_FakeConfig(), provider=_FakeProvider("[]"), memory=mem, knowledge=know,
    )
    assert report["turns_seen"] == 0
    assert report["merged"] == 1
