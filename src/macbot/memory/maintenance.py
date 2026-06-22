"""Memory maintenance — the scheduled "sleep" run.

Folds the episodic turn log into durable knowledge memory, then tidies that
store. Designed to run nightly from the cron service, but also callable on
demand (CLI ``son memory maintain`` / the ``run_memory_maintenance`` tool).

The flow:
1. Read un-consolidated turns from the SQLite log.
2. One LLM call distills them into lessons / preferences / facts, each tagged
   with a domain and importance.
3. Apply the insights (per-key writes; preferences/lessons overwrite by
   key, which is how contradictions resolve).
4. fsck: merge duplicates, expire stale low-value memories.
5. Mark turns consolidated and prune the old episodic log.

The whole thing is best-effort: any step may fail (no API key, bad JSON) without
breaking the rest. The tidy pass (merge/expire) runs even when distillation is
skipped.
"""

import json
import logging
import re
from typing import Any

from macbot.memory.database import AgentMemory
from macbot.memory.knowledge import KnowledgeMemory

logger = logging.getLogger(__name__)

_DISTILL_SYSTEM = """You are the memory consolidation step of a personal macOS \
assistant. You are given a log of recent agent turns (what the user asked, which \
tools ran, the outcome). Extract durable, reusable knowledge worth remembering \
across future sessions — stable user preferences, facts about the user, and \
techniques/lessons. Ignore one-off task details, transient state, and anything \
that won't matter next week.

Return ONLY a JSON array (no prose, no code fences). Each element:
{
  "kind": "lesson" | "preference" | "fact",
  "key": "<topic for lesson, category for preference, omit for fact>",
  "text": "<the knowledge, written to be useful out of context>",
  "domain": "<one of: finances, mail, calendar, documents, health, travel, coding, contacts, general>",
  "importance": <1-5, 5 = essential and permanent>
}
Return [] if nothing is worth keeping."""


def _build_distill_prompt(turns: list[dict[str, Any]]) -> str:
    lines = ["Recent agent turns:\n"]
    for t in turns:
        tools = ", ".join(t.get("tools_used") or []) or "none"
        lines.append(
            f"- [{t.get('domain', 'general')}] goal: {t.get('goal', '')!r} | "
            f"tools: {tools} | outcome: {t.get('outcome', '')} | "
            f"result: {(t.get('summary') or '')[:200]}"
        )
    return "\n".join(lines)


def _parse_insights(text: str) -> list[dict[str, Any]]:
    """Extract the JSON array of insights from a model response."""
    if not text:
        return []
    cleaned = text.strip()
    # Strip code fences if the model added them despite instructions.
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.MULTILINE).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if not match:
            logger.warning("Memory distillation returned non-JSON output; skipping")
            return []
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            logger.warning("Memory distillation JSON could not be parsed; skipping")
            return []
    if not isinstance(data, list):
        return []
    return [d for d in data if isinstance(d, dict)]


async def _distill(turns: list[dict[str, Any]], config: Any, provider: Any) -> list[dict[str, Any]]:
    """Call the LLM once to turn raw turns into structured insights."""
    from macbot.providers.base import Message

    if provider is None:
        from macbot.providers.litellm_provider import LiteLLMProvider
        model = config.get_model()
        provider = LiteLLMProvider(
            model=model,
            api_key=config.get_api_key_for_model(model),
            api_base=config.get_api_base_for_model(model),
        )

    prompt = _build_distill_prompt(turns)
    resp = await provider.chat(
        messages=[Message(role="user", content=prompt)],
        system_prompt=_DISTILL_SYSTEM,
    )
    return _parse_insights(resp.content or "")


def _apply_insight(knowledge: KnowledgeMemory, ins: dict[str, Any]) -> bool:
    """Apply one insight to knowledge memory. Returns True if applied."""
    kind = str(ins.get("kind", "")).lower()
    text = str(ins.get("text", "")).strip()
    if not text:
        return False
    domain = ins.get("domain")
    try:
        importance = int(ins.get("importance", 3))
    except (TypeError, ValueError):
        importance = 3
    importance = max(1, min(5, importance))
    key = str(ins.get("key", "")).strip()

    if kind == "lesson":
        knowledge.add_lesson(key or text[:48], text, domain=domain, importance=importance, source="auto")
    elif kind == "preference":
        knowledge.set_preference(key or (domain or "general"), text, domain=domain, importance=importance, source="auto")
    elif kind == "fact":
        knowledge.add_fact(text, domain=domain, importance=importance, source="auto")
    else:
        return False
    return True


async def run_maintenance(
    config: Any = None,
    provider: Any = None,
    memory: AgentMemory | None = None,
    knowledge: KnowledgeMemory | None = None,
) -> dict[str, Any]:
    """Run the full memory maintenance pass. Returns a report of what happened.

    Args:
        config: Settings (loaded from defaults if not given).
        provider: Optional pre-built LLM provider (mainly for tests).
        memory: Optional AgentMemory instance (for tests).
        knowledge: Optional KnowledgeMemory instance (for tests).
    """
    if config is None:
        from macbot.config import settings as config

    memory = memory or AgentMemory()
    knowledge = knowledge or KnowledgeMemory()

    report: dict[str, Any] = {
        "turns_seen": 0,
        "distilled": 0,
        "merged": 0,
        "expired": 0,
        "pruned": 0,
        "errors": [],
    }

    turns = memory.get_unconsolidated_turns()
    report["turns_seen"] = len(turns)

    if turns:
        try:
            insights = await _distill(turns, config, provider)
            for ins in insights:
                if _apply_insight(knowledge, ins):
                    report["distilled"] += 1
            memory.mark_turns_consolidated([t["id"] for t in turns])
        except Exception as e:  # noqa: BLE001 - best-effort; record and continue
            logger.exception("Memory distillation failed")
            report["errors"].append(f"distill: {e}")

    # fsck: dedupe + expire, even when distillation was skipped/failed.
    try:
        report["merged"] = knowledge.merge_similar()
    except Exception as e:  # noqa: BLE001
        logger.exception("merge_similar failed")
        report["errors"].append(f"merge: {e}")

    try:
        report["expired"] = knowledge.expire_stale(
            max_age_days=getattr(config, "memory_retention_days", 90),
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("expire_stale failed")
        report["errors"].append(f"expire: {e}")

    try:
        report["pruned"] = memory.clear_old_records(
            days=getattr(config, "memory_retention_days", 90),
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("clear_old_records failed")
        report["errors"].append(f"prune: {e}")

    logger.info(
        "Memory maintenance: %d turns → %d insights, %d merged, %d expired, %d pruned",
        report["turns_seen"], report["distilled"], report["merged"],
        report["expired"], report["pruned"],
    )
    return report
