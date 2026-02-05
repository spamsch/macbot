"""Pydantic models for the Skills system."""

from __future__ import annotations

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

    def get_tool_schemas(self, task_registry: TaskRegistry) -> list[dict[str, Any]]:
        """Get tool schemas for tasks this skill references.

        Args:
            task_registry: Registry of available tasks.

        Returns:
            List of tool schemas for the skill's tasks.
        """
        schemas = []
        for task_name in self.tasks:
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
