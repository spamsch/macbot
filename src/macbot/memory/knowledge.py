"""Knowledge memory module for persistent agent learning.

Stores lessons learned, user preferences, and user facts in a human-readable
YAML file that persists across agent runs and is loaded into the system prompt.

Each item carries metadata used for scoped recall and maintenance:
``domain`` (list of coarse tags), ``importance`` (1-5), ``created``/``updated``/
``last_used`` dates, an optional ``expires`` date, and ``source`` ("user" items
are never auto-expired). Old files without these fields still load — missing
fields are filled with defaults on read.

Recall is scoped: ``format_for_prompt(query=...)`` scores items against the
current turn so "help me with finances" surfaces finance memories rather than
the entire store. The nightly maintenance job uses ``merge_similar`` and
``expire_stale`` to keep the file tidy.
"""

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from macbot.memory.tagging import score_domains

_DATE_FMT = "%Y-%m-%d"
DEFAULT_IMPORTANCE = 3


def _today() -> str:
    return datetime.now().strftime(_DATE_FMT)


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, _DATE_FMT)
    except (ValueError, TypeError):
        return None


def _normalize_text(text: str) -> str:
    """Lowercase, collapse whitespace, drop trailing punctuation for dedup."""
    return re.sub(r"\s+", " ", text.strip().lower()).rstrip(".,;:!?")


def _as_domain_list(domain: Any) -> list[str]:
    if domain is None:
        return []
    if isinstance(domain, str):
        return [domain] if domain else []
    if isinstance(domain, list):
        return [str(d) for d in domain if d]
    return []


# The text field that carries the human-readable content for each section.
_TEXT_KEY = {
    "lessons_learned": "lesson",
    "user_preferences": "preference",
    "user_facts": "fact",
}
_SECTIONS = ("lessons_learned", "user_preferences", "user_facts")


class KnowledgeMemory:
    """Persistent agent knowledge memory stored in YAML format."""

    def __init__(self, path: str = "~/.macbot/memory.yaml"):
        """Initialize knowledge memory.

        Args:
            path: Path to the memory YAML file (supports ~ expansion)
        """
        self.path = Path(os.path.expanduser(path))
        self._data: dict[str, Any] | None = None

    def load(self) -> dict[str, Any]:
        """Load memory from file, ensuring sections and item defaults exist."""
        if self._data is not None:
            return self._data

        if self.path.exists():
            with open(self.path) as f:
                self._data = yaml.safe_load(f) or {}
        else:
            self._data = {}

        for section in _SECTIONS:
            if section not in self._data:
                self._data[section] = []
            # Backfill metadata defaults on legacy items.
            for item in self._data[section]:
                self._fill_defaults(item)

        return self._data

    @staticmethod
    def _fill_defaults(item: dict[str, Any]) -> dict[str, Any]:
        """Ensure an item has all metadata fields (mutates in place)."""
        item.setdefault("domain", [])
        item["domain"] = _as_domain_list(item.get("domain"))
        item.setdefault("importance", DEFAULT_IMPORTANCE)
        item.setdefault("source", "auto")
        item.setdefault("created", item.get("added") or _today())
        item.setdefault("updated", item.get("created"))
        item.setdefault("last_used", None)
        item.setdefault("expires", None)
        return item

    def save(self) -> None:
        """Save memory to file with timestamp header."""
        if self._data is None:
            return

        self.path.parent.mkdir(parents=True, exist_ok=True)

        header = (
            "# Agent Memory - Auto-updated by macbot\n"
            f"# Last updated: {datetime.now().isoformat()}\n\n"
        )

        with open(self.path, "w") as f:
            f.write(header)
            yaml.dump(
                self._data, f, default_flow_style=False, allow_unicode=True,
                sort_keys=False,
            )

    # -------------------------------------------------------------------------
    # Writers
    # -------------------------------------------------------------------------

    def add_lesson(
        self,
        topic: str,
        lesson: str,
        domain: Any = None,
        importance: int = DEFAULT_IMPORTANCE,
        source: str = "auto",
        ttl_days: int | None = None,
    ) -> None:
        """Add or update a lesson learned (keyed by topic)."""
        data = self.load()
        domains = _as_domain_list(domain) or score_domains(f"{topic} {lesson}").keys()
        domains = list(domains)
        expires = None
        if ttl_days:
            from datetime import timedelta
            expires = (datetime.now() + timedelta(days=ttl_days)).strftime(_DATE_FMT)

        for item in data["lessons_learned"]:
            if item.get("topic") == topic:
                item["lesson"] = lesson
                item["updated"] = _today()
                item["domain"] = domains or item.get("domain", [])
                item["importance"] = importance
                item["source"] = source
                if expires:
                    item["expires"] = expires
                self.save()
                return

        data["lessons_learned"].append(self._fill_defaults({
            "topic": topic,
            "lesson": lesson,
            "domain": domains,
            "importance": importance,
            "source": source,
            "created": _today(),
            "updated": _today(),
            "expires": expires,
        }))
        self.save()

    def set_preference(
        self,
        category: str,
        preference: str,
        domain: Any = None,
        importance: int = DEFAULT_IMPORTANCE,
        source: str = "user",
    ) -> None:
        """Set or update a user preference (keyed by category).

        Preferences default to ``source="user"`` — they're stated intent and
        shouldn't be auto-expired. Updating a category overwrites it, which is
        how contradictions resolve ("output: terse" replaces "output: verbose").
        """
        data = self.load()
        domains = _as_domain_list(domain) or list(score_domains(f"{category} {preference}").keys())

        for item in data["user_preferences"]:
            if item.get("category") == category:
                item["preference"] = preference
                item["updated"] = _today()
                item["domain"] = domains or item.get("domain", [])
                item["importance"] = max(importance, item.get("importance", importance))
                item["source"] = source
                self.save()
                return

        data["user_preferences"].append(self._fill_defaults({
            "category": category,
            "preference": preference,
            "domain": domains,
            "importance": importance,
            "source": source,
            "created": _today(),
            "updated": _today(),
        }))
        self.save()

    def add_fact(
        self,
        fact: str,
        domain: Any = None,
        importance: int = DEFAULT_IMPORTANCE,
        source: str = "auto",
    ) -> None:
        """Add a fact about the user. Skips exact duplicates."""
        data = self.load()
        norm = _normalize_text(fact)
        for item in data["user_facts"]:
            if _normalize_text(item.get("fact", "")) == norm:
                # Refresh metadata on the existing fact instead of duplicating.
                item["updated"] = _today()
                item["importance"] = max(importance, item.get("importance", importance))
                if source == "user":
                    item["source"] = "user"
                return
        domains = _as_domain_list(domain) or list(score_domains(fact).keys())
        data["user_facts"].append(self._fill_defaults({
            "fact": fact,
            "domain": domains,
            "importance": importance,
            "source": source,
            "created": _today(),
            "updated": _today(),
        }))
        self.save()

    # -------------------------------------------------------------------------
    # Removers
    # -------------------------------------------------------------------------

    def remove_lesson(self, topic: str) -> bool:
        """Remove a lesson by topic."""
        data = self.load()
        for i, item in enumerate(data["lessons_learned"]):
            if item.get("topic") == topic:
                del data["lessons_learned"][i]
                self.save()
                return True
        return False

    def remove_preference(self, category: str) -> bool:
        """Remove a preference by category."""
        data = self.load()
        for i, item in enumerate(data["user_preferences"]):
            if item.get("category") == category:
                del data["user_preferences"][i]
                self.save()
                return True
        return False

    def remove_fact(self, fact: str) -> bool:
        """Remove a user fact (exact match)."""
        data = self.load()
        for i, item in enumerate(data["user_facts"]):
            if item.get("fact") == fact:
                del data["user_facts"][i]
                self.save()
                return True
        return False

    def get_all(self) -> dict[str, Any]:
        """Get all memory contents."""
        return self.load()

    # -------------------------------------------------------------------------
    # Retrieval
    # -------------------------------------------------------------------------

    @staticmethod
    def _item_text(section: str, item: dict[str, Any]) -> str:
        return str(item.get(_TEXT_KEY[section], ""))

    def _score_item(
        self, section: str, item: dict[str, Any],
        query_domains: set[str], query_words: set[str],
    ) -> float:
        """Relevance score: importance + domain overlap + keyword overlap + recency."""
        importance = int(item.get("importance", DEFAULT_IMPORTANCE))
        item_domains = set(_as_domain_list(item.get("domain")))
        domain_overlap = len(item_domains & query_domains)

        text_low = self._item_text(section, item).lower()
        if section == "lessons_learned":
            text_low += " " + str(item.get("topic", "")).lower()
        kw_overlap = sum(1 for w in query_words if w in text_low)

        recency = 0
        updated = _parse_date(item.get("updated") or item.get("created"))
        if updated and (datetime.now() - updated).days <= 30:
            recency = 1

        return importance + 3 * domain_overlap + min(kw_overlap, 3) + recency

    def search(
        self, query: str, domain: str | None = None, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Return memory items most relevant to a query (for the recall tool).

        Marks returned items as used (updates ``last_used``) so the maintenance
        job can expire genuinely stale memories rather than recently-recalled ones.
        """
        data = self.load()
        query_domains = set(score_domains(query))
        if domain:
            query_domains.add(domain)
        query_words = {w for w in re.findall(r"\b\w+\b", query.lower()) if len(w) >= 4}

        scored: list[tuple[float, str, dict[str, Any]]] = []
        for section in _SECTIONS:
            for item in data[section]:
                score = self._score_item(section, item, query_domains, query_words)
                scored.append((score, section, item))

        scored.sort(key=lambda t: t[0], reverse=True)
        top = scored[:limit]

        results: list[dict[str, Any]] = []
        changed = False
        for score, section, item in top:
            item["last_used"] = _today()
            changed = True
            results.append({
                "section": section,
                "text": self._item_text(section, item),
                "topic": item.get("topic"),
                "category": item.get("category"),
                "domain": _as_domain_list(item.get("domain")),
                "importance": item.get("importance", DEFAULT_IMPORTANCE),
                "score": score,
            })
        if changed:
            self.save()
        return results

    def format_for_prompt(
        self,
        query: str | None = None,
        max_items: int | None = None,
        top_k: int | None = None,
    ) -> str:
        """Format memory as markdown for system prompt injection.

        Args:
            query: Current turn goal. When given, items are scored for relevance
                and only the most relevant are injected (scoped recall). User
                preferences and high-importance items are always included.
            max_items: Legacy cap — when no query is given, keep the last N items
                per section.
            top_k: When a query is given, cap the total number of injected items.

        Returns:
            Markdown-formatted string, or empty string if no memory.
        """
        data = self.load()

        if query:
            selected = self._select_relevant(data, query, top_k or 20)
        else:
            selected = {}
            for section in _SECTIONS:
                items = data[section]
                if max_items is not None:
                    items = items[-max_items:]
                selected[section] = items

        sections_md: list[str] = []
        titles = {
            "lessons_learned": "### Lessons Learned",
            "user_preferences": "### User Preferences",
            "user_facts": "### User Facts",
        }
        for section in _SECTIONS:
            items = selected.get(section, [])
            if not items:
                continue
            lines = [titles[section]]
            for item in items:
                if section == "lessons_learned":
                    lines.append(f"- **{item['topic']}**: {item['lesson']}")
                elif section == "user_preferences":
                    lines.append(f"- **{item['category']}**: {item['preference']}")
                else:
                    lines.append(f"- {item['fact']}")
            sections_md.append("\n".join(lines))

        if not sections_md:
            return ""

        return "## Agent Memory\n\n" + "\n\n".join(sections_md)

    def _select_relevant(
        self, data: dict[str, Any], query: str, top_k: int
    ) -> dict[str, list[dict[str, Any]]]:
        """Pick the most relevant items for a query, keeping section grouping.

        Always keeps user preferences and importance>=4 items; fills the rest of
        the budget with the highest-scoring items.
        """
        query_domains = set(score_domains(query))
        query_words = {w for w in re.findall(r"\b\w+\b", query.lower()) if len(w) >= 4}

        ranked: list[tuple[bool, float, str, dict[str, Any]]] = []
        for section in _SECTIONS:
            for item in data[section]:
                always = (
                    item.get("source") == "user"
                    or int(item.get("importance", DEFAULT_IMPORTANCE)) >= 4
                )
                score = self._score_item(section, item, query_domains, query_words)
                ranked.append((always, score, section, item))

        # Always-keep first, then by score; take the top_k.
        ranked.sort(key=lambda t: (t[0], t[1]), reverse=True)
        chosen = ranked[:top_k]

        out: dict[str, list[dict[str, Any]]] = {s: [] for s in _SECTIONS}
        chosen_ids = {id(item) for _, _, _, item in chosen}
        # Preserve each section's original order among chosen items.
        for section in _SECTIONS:
            for item in data[section]:
                if id(item) in chosen_ids:
                    out[section].append(item)
        return out

    # -------------------------------------------------------------------------
    # Maintenance (used by the nightly sleep job)
    # -------------------------------------------------------------------------

    def merge_similar(self) -> int:
        """Drop normalized-duplicate lessons and facts, keeping the best copy.

        Keeps the highest-importance / most-recently-updated copy. Preferences
        are keyed by category and can't duplicate. Returns the number removed.
        """
        data = self.load()
        removed = 0
        for section in ("lessons_learned", "user_facts"):
            seen: dict[str, dict[str, Any]] = {}
            kept: list[dict[str, Any]] = []
            for item in data[section]:
                norm = _normalize_text(self._item_text(section, item))
                if norm in seen:
                    removed += 1
                    winner = self._pick_better(seen[norm], item)
                    # Replace the kept copy if this one wins.
                    if winner is item:
                        kept[kept.index(seen[norm])] = item
                        seen[norm] = item
                    continue
                seen[norm] = item
                kept.append(item)
            data[section] = kept
        if removed:
            self.save()
        return removed

    @staticmethod
    def _pick_better(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
        """Return the higher-importance, then more-recent, of two items."""
        ia, ib = a.get("importance", DEFAULT_IMPORTANCE), b.get("importance", DEFAULT_IMPORTANCE)
        if ia != ib:
            return a if ia > ib else b
        da = _parse_date(a.get("updated") or a.get("created")) or datetime.min
        db = _parse_date(b.get("updated") or b.get("created")) or datetime.min
        return a if da >= db else b

    def expire_stale(
        self,
        now: datetime | None = None,
        max_age_days: int = 90,
        min_importance_keep: int = 4,
    ) -> int:
        """Remove expired and stale low-value auto memories.

        Removes an item when:
        - it has an ``expires`` date in the past, OR
        - it is ``source="auto"`` with importance below ``min_importance_keep``
          and hasn't been used/updated within ``max_age_days``.

        User-entered items and high-importance items are never auto-removed.
        Returns the number removed.
        """
        now = now or datetime.now()
        data = self.load()
        removed = 0
        for section in _SECTIONS:
            kept: list[dict[str, Any]] = []
            for item in data[section]:
                expires = _parse_date(item.get("expires"))
                if expires and expires < now:
                    removed += 1
                    continue

                source = item.get("source", "auto")
                importance = int(item.get("importance", DEFAULT_IMPORTANCE))
                if source == "user" or importance >= min_importance_keep:
                    kept.append(item)
                    continue

                last = _parse_date(
                    item.get("last_used") or item.get("updated") or item.get("created")
                )
                age_days = (now - last).days if last else max_age_days + 1
                if age_days > max_age_days:
                    removed += 1
                    continue
                kept.append(item)
            data[section] = kept
        if removed:
            self.save()
        return removed
