"""Pydantic models for the Skills system."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from macbot.tasks.registry import TaskRegistry


class Skill(BaseModel):
    """A skill that provides declarative guidance for the agent.

    Skills improve agent reliability by providing:
    - Examples of how to handle requests
    - Safe defaults for parameters
    - Confirmation rules before destructive actions
    - Behavior notes for edge cases
    """

    id: str = Field(description="Unique identifier for the skill")
    name: str = Field(description="Human-readable name")
    description: str = Field(description="Brief description of what this skill does")

    # Associated apps/tools
    apps: list[str] = Field(
        default_factory=list,
        description="macOS apps this skill works with (e.g., Mail, Calendar)",
    )
    tasks: list[str] = Field(
        default_factory=list,
        description="Task names this skill provides guidance for",
    )
    essential_tasks: list[str] | None = Field(
        default=None,
        description="Subset of tasks for compact/minimal context profiles (Pico). "
        "None = fall back to full tasks list; [] = exclude skill entirely in compact mode.",
    )

    # Guidance content
    examples: list[str] = Field(
        default_factory=list,
        description="Example prompts showing how users might invoke this skill",
    )
    safe_defaults: dict[str, Any] = Field(
        default_factory=dict,
        description="Default parameter values for safety (e.g., days=7, limit=20)",
    )
    confirm_before_write: list[str] = Field(
        default_factory=list,
        description="Actions that require user confirmation (e.g., 'delete', 'send')",
    )
    requires_permissions: list[str] = Field(
        default_factory=list,
        description="macOS permissions required (e.g., 'Automation:Mail')",
    )

    # Additional keywords for query matching (e.g., multilingual terms)
    keywords: list[str] = Field(
        default_factory=list,
        description="Extra keywords for query matching (e.g., German equivalents)",
    )

    # Markdown body with detailed behavior notes
    body: str = Field(
        default="",
        description="Markdown content with detailed behavior guidance",
    )

    # Extension mechanism
    extends: str | None = Field(
        default=None,
        description="ID of built-in skill to extend (merges examples, tasks, etc.)",
    )

    # Extra frontmatter fields (for AgentSkills standard compatibility)
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Extra frontmatter fields not part of the core schema (e.g., license, compatibility, homepage)",
    )

    # Metadata
    source_path: Path | None = Field(
        default=None,
        description="Path to the SKILL.md file this was loaded from",
    )
    is_builtin: bool = Field(
        default=False,
        description="Whether this is a built-in skill (vs user-defined)",
    )
    enabled: bool = Field(
        default=True,
        description="Whether this skill is currently enabled",
    )

    # Common words that appear in many skills — not useful for disambiguation
    _STOP_WORDS = frozenset({
        "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "can", "shall", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "into", "about", "like",
        "and", "or", "but", "not", "no", "if", "then", "so", "up", "out",
        "it", "its", "i", "me", "my", "you", "your", "we", "our", "they",
        "this", "that", "what", "which", "who", "how", "when", "where",
        "all", "any", "some", "each", "every", "much", "many", "more",
        "new", "get", "set", "show", "list", "create", "add", "make",
        "find", "search", "check", "update", "delete", "remove", "run",
        "open", "close", "start", "stop", "send", "read", "write",
        "using", "use", "via", "also", "just", "please", "help",
        "today", "tomorrow", "yesterday", "now", "here", "there",
        "call", "name", "last", "first", "next", "current",
    })

    def matches_query(self, query: str) -> float:
        """Score how relevant this skill is to a user query.

        Returns a score between 0.0 (no match) and 1.0 (strong match).
        Uses keyword matching against skill name, description, apps,
        task names, and examples. Filters out common stop words.
        """
        if not query:
            return 0.0

        query_lower = query.lower()
        all_words = set(re.findall(r"[a-z]+", query_lower))
        words = all_words - self._STOP_WORDS
        score = 0.0

        # App name match (strong signal) — uses full query, not just content words
        for app in self.apps:
            app_lower = app.lower()
            if app_lower in query_lower:
                score = max(score, 0.9)
            app_base = app_lower.replace(".app", "").replace(" ", "")
            if app_base in query_lower:
                score = max(score, 0.9)

        # Explicit keywords match (supports multilingual terms)
        for kw in self.keywords:
            if kw.lower() in query_lower:
                score = max(score, 0.85)

        # No content words after filtering? Can't match on keywords.
        if not words:
            return score

        # Skill name/id match
        name_words = set(re.findall(r"[a-z]+", self.name.lower())) - self._STOP_WORDS
        id_words = set(re.findall(r"[a-z]+", self.id.lower())) - self._STOP_WORDS
        if name_words & words:
            score = max(score, 0.8)
        if id_words & words:
            score = max(score, 0.7)

        # Task name match — only match on non-verb parts of task names
        # e.g., "reminder" in "create_reminder" matches, but "create" doesn't
        for task_name in self.tasks:
            task_words = set(task_name.lower().split("_")) - self._STOP_WORDS
            if task_words & words:
                score = max(score, 0.7)

        # Description keyword overlap (needs 2+ content word matches)
        desc_words = set(re.findall(r"[a-z]+", self.description.lower())) - self._STOP_WORDS
        overlap = words & desc_words
        if len(overlap) >= 2:
            score = max(score, min(0.6, 0.15 * len(overlap)))

        # Example match (needs 2+ content word matches)
        for example in self.examples:
            example_words = set(re.findall(r"[a-z]+", example.lower())) - self._STOP_WORDS
            overlap = words & example_words
            if len(overlap) >= 2:
                score = max(score, 0.5)

        return score

    def get_effective_tasks(self, compact: bool = False) -> list[str]:
        """Return the task list appropriate for the context profile.

        Args:
            compact: If True, prefer essential_tasks when available.

        Returns:
            Task name list. When compact=True and essential_tasks is not None,
            returns essential_tasks; otherwise returns full tasks list.
        """
        if compact and self.essential_tasks is not None:
            return self.essential_tasks
        return self.tasks

    def get_tool_schemas(
        self, task_registry: TaskRegistry, compact: bool = False,
    ) -> list[dict[str, Any]]:
        """Get tool schemas for tasks this skill references.

        Args:
            task_registry: Registry of available tasks.
            compact: If True, use essential_tasks when available.

        Returns:
            List of tool schemas for the skill's tasks.
        """
        schemas = []
        for task_name in self.get_effective_tasks(compact):
            task = task_registry.get(task_name)
            if task:
                schemas.append(task.to_tool_schema())
        return schemas

    def format_for_prompt(self, task_registry: TaskRegistry | None = None) -> str:
        """Format this skill for inclusion in the agent's system prompt.

        Args:
            task_registry: Optional registry to validate tasks exist.

        Returns:
            Formatted skill text for the system prompt.
        """
        lines = [f"### {self.name}"]
        lines.append(self.description)

        if self.tasks:
            lines.append(f"\n**Tools:** {', '.join(self.tasks)}")

        if self.examples:
            lines.append("\n**Examples:**")
            for example in self.examples[:5]:  # Limit to 5 examples
                lines.append(f"- \"{example}\"")

        if self.safe_defaults:
            defaults_str = ", ".join(f"{k}={v}" for k, v in self.safe_defaults.items())
            lines.append(f"\n**Defaults:** {defaults_str}")

        if self.confirm_before_write:
            actions = ", ".join(self.confirm_before_write)
            lines.append(f"\n**Important:** Ask for confirmation before: {actions}")

        if self.body.strip():
            lines.append(f"\n{self.body.strip()}")

        return "\n".join(lines)

    def format_for_prompt_compact(self) -> str:
        """Format this skill compactly for reduced-context profiles.

        Returns only essential info: name, description, tools, defaults,
        and confirmation rules. No examples, no body.
        Uses essential_tasks when available.
        """
        effective = self.get_effective_tasks(compact=True)
        lines = [f"### {self.name}"]
        lines.append(self.description)

        if effective:
            lines.append(f"**Tools:** {', '.join(effective)}")

        if self.safe_defaults:
            defaults_str = ", ".join(f"{k}={v}" for k, v in self.safe_defaults.items())
            lines.append(f"**Defaults:** {defaults_str}")

        if self.confirm_before_write:
            lines.append(f"**Confirm before:** {', '.join(self.confirm_before_write)}")

        return "\n".join(lines)


class SkillsConfig(BaseModel):
    """Configuration for skills enable/disable state.

    Persisted to ~/.macbot/skills.json
    """

    # Map of skill_id -> enabled state
    enabled_skills: dict[str, bool] = Field(
        default_factory=dict,
        description="Map of skill ID to enabled state",
    )

    def is_enabled(self, skill_id: str, default: bool = True) -> bool:
        """Check if a skill is enabled.

        Args:
            skill_id: The skill identifier
            default: Default value if not explicitly configured

        Returns:
            Whether the skill is enabled
        """
        return self.enabled_skills.get(skill_id, default)

    def set_enabled(self, skill_id: str, enabled: bool) -> None:
        """Set the enabled state for a skill.

        Args:
            skill_id: The skill identifier
            enabled: Whether to enable or disable
        """
        self.enabled_skills[skill_id] = enabled
