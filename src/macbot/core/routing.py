"""Hybrid routing engine for per-turn model selection.

The router keeps the agent on a cheap default model and escalates to a stronger
one only when a turn is genuinely harder. The decision is made once, up front,
from three signals and then held for the whole turn so the model never
flip-flops mid-turn:

1. **Skills** selected for the turn (strong signal — the agent's own relevance
   pass already decided which skills are in play).
2. **Keywords** in the user message — scored, word-boundary matched, with
   per-keyword weights and exclusions so a single generic word can't escalate.
3. **Complexity** of the request — long/multi-skill/"hard verb" turns escalate
   regardless of topic.

Models are named in `tiers` (e.g. fast → smart) and ordered weak→strong, so a
route or escalation says "tier: smart" instead of repeating a model string, and
the engine can compare strengths to enforce escalate-only behavior.

Config lives in ~/.macbot/routing.json. No file / no routes = no routing.

Backward compatibility: the older schema (routes with a literal `model` and a
flat list of string `keywords`, no `tiers` block) still loads and works. Plain
string keywords get weight 1.0; `resolve()`/`resolve_intent()` keep their
first-match semantics.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path.home() / ".macbot" / "routing.json"

# Providers that never need an API key (validated against, not routed on).
_KEYLESS_PROVIDERS = ("pico", "chatgpt")

# Bilingual (EN/DE) verbs that signal a genuinely involved task. Whole-word
# matched. Used by the complexity heuristic; overridable per config.
DEFAULT_HARD_VERBS = [
    "analyze", "analyse", "analysiere", "analysieren",
    "compare", "vergleiche", "vergleich", "vergleichen",
    "summarize", "summarise", "zusammenfassen", "zusammenfassung",
    "explain", "erkläre", "erklär", "erklären",
    "plan", "plane", "planen",
    "debug", "refactor", "optimize", "optimise", "optimiere", "optimieren",
    "research", "recherchiere", "recherche", "recherchieren",
    "investigate", "untersuche", "untersuchen",
    "draft", "entwirf", "entwerfe", "entwerfen",
    "review", "prüfe", "bewerte", "bewerten",
    "troubleshoot", "brainstorm", "design",
]


class Keyword(BaseModel):
    """A weighted keyword. Plain strings in config become weight-1.0 keywords."""

    word: str
    weight: float = 1.0


class Route(BaseModel):
    """A routing rule. Fires on a skill match or a keyword score >= min_score."""

    name: str
    skills: list[str] = Field(default_factory=list)
    keywords: list[Keyword] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    # Target model: either a tier name (resolved via RoutingConfig.tiers) or a
    # literal model string. `tier` takes precedence when both are set.
    tier: str | None = None
    model: str | None = None
    # Minimum total keyword score required to fire on keywords alone.
    min_score: float = 1.0

    @field_validator("keywords", mode="before")
    @classmethod
    def _normalize_keywords(cls, value: Any) -> Any:
        """Accept plain strings or {word, weight} dicts."""
        if not value:
            return []
        normalized = []
        for item in value:
            if isinstance(item, str):
                normalized.append({"word": item})
            else:
                normalized.append(item)
        return normalized


class ComplexityConfig(BaseModel):
    """Heuristic that escalates hard turns regardless of topic."""

    enabled: bool = True
    min_words: int = 40
    multi_skill_threshold: int = 3
    escalate_to: str | None = None  # tier name; defaults to the strongest tier
    hard_verbs: list[str] = Field(default_factory=lambda: list(DEFAULT_HARD_VERBS))


class RoutingConfig(BaseModel):
    """Top-level routing configuration."""

    tiers: dict[str, str] = Field(default_factory=dict)
    order: list[str] = Field(default_factory=list)  # tier names, weak → strong
    default_tier: str | None = None
    complexity: ComplexityConfig = Field(default_factory=ComplexityConfig)
    routes: list[Route] = Field(default_factory=list)
    # Magic words that force the strongest tier for a turn, overriding every
    # other signal. Whole-word, case-insensitive. Set to [] to disable.
    magic_words: list[str] = Field(default_factory=lambda: ["ultrathink"])


class RoutingEngine:
    """Resolves a per-turn model from skills, keywords, and complexity."""

    def __init__(
        self,
        config_path: Path | None = None,
        skills_registry: Any = None,
    ) -> None:
        self._config_path = config_path or DEFAULT_CONFIG_PATH
        self._skills_registry = skills_registry
        self._config = RoutingConfig()
        # tool_name -> set of skill_ids that claim it
        self._tool_to_skills: dict[str, set[str]] = {}
        self._load()

    # ------------------------------------------------------------------ load

    def _load(self) -> None:
        self._config = self._load_config()
        self._build_reverse_index()

    def _load_config(self) -> RoutingConfig:
        if not self._config_path.exists():
            return RoutingConfig()
        try:
            data = json.loads(self._config_path.read_text(encoding="utf-8"))
            return RoutingConfig(**data)
        except Exception as e:
            logger.warning("Failed to load routing config from %s: %s", self._config_path, e)
            return RoutingConfig()

    def _build_reverse_index(self) -> None:
        self._tool_to_skills.clear()
        if self._skills_registry is None:
            return
        for skill in self._skills_registry.list_enabled_skills():
            for task_name in skill.tasks:
                self._tool_to_skills.setdefault(task_name, set()).add(skill.id)

    def reload(self) -> None:
        """Re-read routing.json and rebuild the reverse index."""
        self._load()

    # --------------------------------------------------------------- helpers

    @property
    def has_routes(self) -> bool:
        return len(self._config.routes) > 0

    @property
    def active(self) -> bool:
        """True if the engine can do anything for a turn.

        Beyond explicit routes, the engine is useful whenever tiers are defined:
        complexity escalation and the magic word both need a strongest tier to
        escalate to. So a tiers-only config (no routes) still routes.
        """
        return self.has_routes or bool(self._ordered_models())

    @property
    def config(self) -> RoutingConfig:
        return self._config

    def _route_target_model(self, route: Route) -> str | None:
        """Resolve a route to a concrete model string."""
        if route.tier and route.tier in self._config.tiers:
            return self._config.tiers[route.tier]
        if route.model:
            return route.model
        if route.tier:  # tier name given but not in the tiers map → treat literally
            return route.tier
        return None

    def _ordered_models(self) -> list[str]:
        """Model strings ordered weak → strong, for rank comparisons."""
        cfg = self._config
        if cfg.order:
            return [cfg.tiers.get(t, t) for t in cfg.order]
        if cfg.tiers:
            return list(cfg.tiers.values())
        return []

    def tier_rank(self, model: str, base_model: str | None = None) -> int:
        """Strength rank of a model (higher = stronger).

        With tiers defined, unknown models rank at the floor so escalate-only
        logic never jumps to an unlisted model by accident. With no tiers
        (legacy config), any non-base model outranks the base so route models
        still win in decide().
        """
        ordered = self._ordered_models()
        if ordered:
            if base_model and base_model not in ordered:
                ordered = [base_model] + ordered
            return ordered.index(model) if model in ordered else 0
        # Legacy: no tiers/order — base is the floor, route models outrank it.
        if base_model is not None:
            return 0 if model == base_model else 1
        return 0

    @staticmethod
    def _word_in(word: str, text_lower: str) -> bool:
        w = word.lower().strip()
        if not w:
            return False
        return re.search(rf"\b{re.escape(w)}\b", text_lower) is not None

    def _keyword_score(self, route: Route, text_lower: str) -> float:
        """Weighted keyword score; 0 if any exclusion keyword is present."""
        for ex in route.exclude_keywords:
            if self._word_in(ex, text_lower):
                return 0.0
        score = 0.0
        for kw in route.keywords:
            if self._word_in(kw.word, text_lower):
                score += kw.weight
        return score

    def _is_complex(self, text_lower: str, skill_ids: set[str]) -> bool:
        c = self._config.complexity
        if not c.enabled:
            return False
        if len(re.findall(r"\w+", text_lower)) >= c.min_words:
            return True
        if len(skill_ids) >= c.multi_skill_threshold:
            return True
        return any(self._word_in(v, text_lower) for v in c.hard_verbs)

    def _escalate_model(self) -> str | None:
        cfg = self._config
        if cfg.complexity.escalate_to and cfg.complexity.escalate_to in cfg.tiers:
            return cfg.tiers[cfg.complexity.escalate_to]
        ordered = self._ordered_models()
        return ordered[-1] if ordered else None

    def _strongest_model(self) -> str | None:
        """The strongest configured model (last tier in `order`), or None."""
        ordered = self._ordered_models()
        return ordered[-1] if ordered else None

    def _has_magic_word(self, text_lower: str) -> bool:
        """True if any configured magic word appears as a whole word."""
        return any(self._word_in(w, text_lower) for w in self._config.magic_words)

    # ------------------------------------------------------------- decisions

    def decide(
        self,
        message: str,
        skill_ids: list[str] | None,
        base_model: str,
    ) -> str:
        """Pick the model for a turn from skills, keywords, and complexity.

        Made once, up front. Returns the strongest model any signal asks for,
        or the (tier-resolved) base when nothing fires.

        Args:
            message: The raw user message for this turn.
            skill_ids: Skill IDs selected as relevant for this turn.
            base_model: The configured default model (turn floor).

        Returns:
            The model string to use for the turn.
        """
        cfg = self._config
        base = base_model
        if cfg.default_tier and cfg.default_tier in cfg.tiers:
            base = cfg.tiers[cfg.default_tier]

        text = (message or "").lower()

        # Magic word ("ultrathink"): force the strongest model, overriding every
        # other signal. Works wherever a turn runs — CLI, chat, Telegram, cron.
        if self._has_magic_word(text):
            strongest = self._strongest_model()
            if strongest:
                logger.info("Magic word matched → strongest model %s", strongest)
                return strongest
            logger.warning(
                "Magic word matched but no tiers are configured; staying on %s", base
            )

        if not cfg.routes and not cfg.complexity.enabled:
            return base

        skills = set(skill_ids or [])
        candidates = [base]

        for route in cfg.routes:
            target = self._route_target_model(route)
            if not target:
                continue
            skill_match = bool(route.skills) and bool(skills & set(route.skills))
            keyword_match = self._keyword_score(route, text) >= route.min_score
            if skill_match or keyword_match:
                candidates.append(target)

        if self._is_complex(text, skills):
            escalated = self._escalate_model()
            if escalated:
                candidates.append(escalated)

        return max(candidates, key=lambda m: self.tier_rank(m, base))

    def resolve(self, tool_names: list[str]) -> str | None:
        """Tool-based resolution (first matching route wins).

        Maps called tools → skills → routes. Used by the agent as an
        escalate-only safety net after a tool call reveals a heavier skill.
        Returns None when no route matches.
        """
        if not self._config.routes or not tool_names:
            return None

        active_skills: set[str] = set()
        for tool_name in tool_names:
            active_skills |= self._tool_to_skills.get(tool_name, set())
        if not active_skills:
            return None

        for route in self._config.routes:
            if set(route.skills) & active_skills:
                logger.info("Route '%s' matched tools → %s", route.name, self._route_target_model(route))
                return self._route_target_model(route)
        return None

    def resolve_intent(self, user_message: str) -> str | None:
        """Keyword-based resolution (first matching route wins).

        Word-boundary, weighted, exclusion-aware. Returns the first route whose
        keyword score meets its min_score. Kept for callers/tests that want a
        single keyword verdict; the agent uses decide() instead.
        """
        if not self._config.routes or not user_message:
            return None
        text = user_message.lower()
        for route in self._config.routes:
            if not route.keywords:
                continue
            if self._keyword_score(route, text) >= route.min_score:
                logger.info("Intent route '%s' matched → %s", route.name, self._route_target_model(route))
                return self._route_target_model(route)
        return None

    # -------------------------------------------------------------- validate

    def validate(self, settings: Any = None) -> list[str]:
        """Validate routes against available skills and API keys."""
        warnings: list[str] = []
        if not self._config.routes:
            return warnings

        all_skills: set[str] = set()
        enabled_skills: set[str] = set()
        if self._skills_registry is not None:
            all_skills = {s.id for s in self._skills_registry.list_skills()}
            enabled_skills = {s.id for s in self._skills_registry.list_enabled_skills()}

        for route in self._config.routes:
            for skill_id in route.skills:
                if skill_id not in all_skills:
                    warnings.append(f"Route '{route.name}': skill '{skill_id}' not found")
                elif skill_id not in enabled_skills:
                    warnings.append(f"Route '{route.name}': skill '{skill_id}' is disabled")

            if settings is not None:
                model = self._route_target_model(route)
                if not model:
                    warnings.append(f"Route '{route.name}': no model or tier configured")
                    continue
                api_key = settings.get_api_key_for_model(model)
                provider = model.split("/")[0] if "/" in model else model
                if provider not in _KEYLESS_PROVIDERS and not api_key:
                    warnings.append(f"Route '{route.name}': no API key for provider '{provider}'")

        # Validate tier references.
        for route in self._config.routes:
            if route.tier and self._config.tiers and route.tier not in self._config.tiers and not route.model:
                warnings.append(f"Route '{route.name}': tier '{route.tier}' not defined in tiers")
        if self._config.complexity.escalate_to and self._config.tiers:
            if self._config.complexity.escalate_to not in self._config.tiers:
                warnings.append(
                    f"complexity.escalate_to '{self._config.complexity.escalate_to}' not defined in tiers"
                )

        return warnings
