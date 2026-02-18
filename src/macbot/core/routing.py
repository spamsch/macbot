"""Hybrid routing engine for per-turn model switching.

Allows different skills to use different LLM models. Routes are
defined in ~/.macbot/routing.json and matched against tool calls
made by the agent each turn.

No file / empty routes = current behavior (zero config needed).
"""

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path.home() / ".macbot" / "routing.json"


class Route(BaseModel):
    """A single routing rule mapping skills to a model."""

    name: str
    skills: list[str] = Field(default_factory=list)
    model: str


class RoutingConfig(BaseModel):
    """Top-level routing configuration."""

    routes: list[Route] = Field(default_factory=list)


class RoutingEngine:
    """Resolves tool calls to model strings via skill-based routes.

    Builds a reverse index from tool names to skill IDs, then walks
    routes in order to find the first match.
    """

    def __init__(
        self,
        config_path: Path | None = None,
        skills_registry: Any = None,
    ) -> None:
        """Initialize the routing engine.

        Args:
            config_path: Path to routing.json (default: ~/.macbot/routing.json)
            skills_registry: SkillsRegistry instance for building the
                tool→skill reverse index.
        """
        self._config_path = config_path or DEFAULT_CONFIG_PATH
        self._skills_registry = skills_registry
        self._config = RoutingConfig()
        # tool_name -> set of skill_ids that claim it
        self._tool_to_skills: dict[str, set[str]] = {}

        self._load()

    def _load(self) -> None:
        """Load routing config and build reverse index."""
        self._config = self._load_config()
        self._build_reverse_index()

    def _load_config(self) -> RoutingConfig:
        """Read and parse routing.json."""
        if not self._config_path.exists():
            return RoutingConfig()

        try:
            raw = self._config_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            return RoutingConfig(**data)
        except Exception as e:
            logger.warning("Failed to load routing config from %s: %s", self._config_path, e)
            return RoutingConfig()

    def _build_reverse_index(self) -> None:
        """Build a mapping from tool_name → set of skill_ids."""
        self._tool_to_skills.clear()

        if self._skills_registry is None:
            return

        for skill in self._skills_registry.list_enabled_skills():
            for task_name in skill.tasks:
                self._tool_to_skills.setdefault(task_name, set()).add(skill.id)

    @property
    def has_routes(self) -> bool:
        """True if any routes are configured."""
        return len(self._config.routes) > 0

    @property
    def config(self) -> RoutingConfig:
        """The current routing configuration."""
        return self._config

    def resolve(self, tool_names: list[str]) -> str | None:
        """Resolve a set of tool calls to a model string.

        First-match resolution:
        1. Map called tool names → active skill IDs (via reverse index)
        2. Walk routes in order; first route whose skills overlap wins
        3. Return matched route.model, or None (keep current model)

        Args:
            tool_names: List of tool names from the current turn's tool calls.

        Returns:
            Model string if a route matches, None otherwise.
        """
        if not self._config.routes or not tool_names:
            return None

        # Gather all skill IDs that are associated with the called tools
        active_skills: set[str] = set()
        for tool_name in tool_names:
            skills = self._tool_to_skills.get(tool_name, set())
            active_skills.update(skills)

        if not active_skills:
            return None

        # Walk routes in order — first match wins
        for route in self._config.routes:
            route_skills = set(route.skills)
            if route_skills & active_skills:
                logger.info(
                    "Route '%s' matched (skills: %s) → model: %s",
                    route.name,
                    route_skills & active_skills,
                    route.model,
                )
                return route.model

        return None

    def validate(self, settings: Any = None) -> list[str]:
        """Validate routes against available skills and API keys.

        Args:
            settings: Settings instance for checking API keys.

        Returns:
            List of warning strings (empty = all good).
        """
        warnings: list[str] = []

        if not self._config.routes:
            return warnings

        # Collect skill IDs — check all known skills for "not found",
        # and enabled skills for "disabled" warnings (resolve() only
        # uses enabled skills).
        all_skills: set[str] = set()
        enabled_skills: set[str] = set()
        if self._skills_registry is not None:
            all_skills = {s.id for s in self._skills_registry.list_skills()}
            enabled_skills = {s.id for s in self._skills_registry.list_enabled_skills()}

        for route in self._config.routes:
            # Check for unknown or disabled skills
            for skill_id in route.skills:
                if skill_id not in all_skills:
                    warnings.append(
                        f"Route '{route.name}': skill '{skill_id}' not found"
                    )
                elif skill_id not in enabled_skills:
                    warnings.append(
                        f"Route '{route.name}': skill '{skill_id}' is disabled"
                    )

            # Check API key availability for the route's model
            if settings is not None:
                api_key = settings.get_api_key_for_model(route.model)
                provider = route.model.split("/")[0] if "/" in route.model else route.model
                if provider != "pico" and not api_key:
                    warnings.append(
                        f"Route '{route.name}': no API key for provider '{provider}'"
                    )

        return warnings

    def reload(self) -> None:
        """Re-read routing.json and rebuild the reverse index."""
        self._load()
