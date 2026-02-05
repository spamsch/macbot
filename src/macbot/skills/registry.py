"""Registry for managing skills."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from macbot.skills.loader import discover_skills
from macbot.skills.models import Skill, SkillsConfig

if TYPE_CHECKING:
    from macbot.tasks.registry import TaskRegistry

logger = logging.getLogger(__name__)

# Default paths
USER_SKILLS_DIR = Path.home() / ".macbot" / "skills"
SKILLS_CONFIG_FILE = Path.home() / ".macbot" / "skills.json"


def get_builtin_skills_dir() -> Path:
    """Get the path to built-in skills directory.

    Handles both development and PyInstaller bundled scenarios.
    """
    # Check if running as PyInstaller bundle
    if getattr(sys, "_MEIPASS", None):
        return Path(sys._MEIPASS) / "skills"

    # Development: look relative to the package
    # Walk up from this file to find the project root
    current = Path(__file__).resolve()

    # Try to find skills/ directory relative to the source tree
    # src/macbot/skills/registry.py -> src/macbot/skills -> src/macbot -> src -> project_root
    # Look for a skills/ directory that contains SKILL.md files (not the Python package)
    for _ in range(5):
        current = current.parent
        skills_dir = current / "skills"
        if skills_dir.exists() and skills_dir.is_dir():
            # Check if this contains actual skill directories (with SKILL.md)
            # vs being the Python package (with __init__.py)
            has_skill_files = any(
                (d / "SKILL.md").exists()
                for d in skills_dir.iterdir()
                if d.is_dir()
            )
            if has_skill_files:
                return skills_dir

    # Fallback: relative to current working directory
    return Path.cwd() / "skills"


class SkillsRegistry:
    """Registry for loading and managing skills.

    Loads skills from:
    1. Built-in skills directory (skills/)
    2. User skills directory (~/.macbot/skills/)

    User skills with the same ID override built-in skills.
    Enable/disable state is persisted to ~/.macbot/skills.json
    """

    def __init__(
        self,
        builtin_dir: Path | None = None,
        user_dir: Path | None = None,
        config_file: Path | None = None,
    ) -> None:
        """Initialize the registry.

        Args:
            builtin_dir: Path to built-in skills (default: auto-detected)
            user_dir: Path to user skills (default: ~/.macbot/skills/)
            config_file: Path to config file (default: ~/.macbot/skills.json)
        """
        self.builtin_dir = builtin_dir or get_builtin_skills_dir()
        self.user_dir = user_dir or USER_SKILLS_DIR
        self.config_file = config_file or SKILLS_CONFIG_FILE

        self._skills: dict[str, Skill] = {}
        self._config = SkillsConfig()

        self._load_config()
        self._load_skills()

    def _load_config(self) -> None:
        """Load skills configuration from disk."""
        if not self.config_file.exists():
            return

        try:
            content = self.config_file.read_text(encoding="utf-8")
            data = json.loads(content)
            self._config = SkillsConfig(**data)
            logger.debug(f"Loaded skills config from {self.config_file}")
        except Exception as e:
            logger.warning(f"Failed to load skills config: {e}")
            self._config = SkillsConfig()

    def _save_config(self) -> None:
        """Save skills configuration to disk."""
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            content = self._config.model_dump_json(indent=2)
            self.config_file.write_text(content, encoding="utf-8")
            logger.debug(f"Saved skills config to {self.config_file}")
        except Exception as e:
            logger.warning(f"Failed to save skills config: {e}")

    def _merge_skill(self, base: Skill, extension: Skill) -> Skill:
        """Merge extension skill into base skill using simple merge strategy.

        Merge rules:
        - Lists (apps, tasks, examples, etc.): append (deduplicated)
        - Dicts (safe_defaults): merge, extension values win on conflict
        - Strings (name, description, body): replace if provided in extension

        Args:
            base: The built-in skill being extended.
            extension: The user skill providing extensions.

        Returns:
            Merged skill.
        """
        # Helper to dedupe while preserving order
        def dedupe_list(items: list) -> list:
            return list(dict.fromkeys(items))

        # Determine if extension provides a meaningful name/description
        # (not just using id as fallback)
        ext_name = extension.name if extension.name != extension.id else base.name
        ext_description = extension.description if extension.description else base.description

        return Skill(
            id=base.id,
            name=ext_name,
            description=ext_description,
            apps=dedupe_list(base.apps + extension.apps),
            tasks=dedupe_list(base.tasks + extension.tasks),
            examples=base.examples + extension.examples,  # Allow duplicates for examples
            safe_defaults={**base.safe_defaults, **extension.safe_defaults},
            confirm_before_write=dedupe_list(base.confirm_before_write + extension.confirm_before_write),
            requires_permissions=dedupe_list(base.requires_permissions + extension.requires_permissions),
            body=extension.body if extension.body.strip() else base.body,
            source_path=extension.source_path,
            is_builtin=False,  # Merged skill is considered user skill
            enabled=extension.enabled,
            extends=None,  # Clear extends on merged result
        )

    def _load_skills(self) -> None:
        """Load all skills from disk."""
        self._skills.clear()

        # Load built-in skills first
        builtin_skills = discover_skills(self.builtin_dir, is_builtin=True)
        for skill in builtin_skills:
            skill.enabled = self._config.is_enabled(skill.id, default=True)
            self._skills[skill.id] = skill
            logger.debug(f"Loaded built-in skill: {skill.id}")

        # Load user skills (can extend or override built-in by id)
        user_skills = discover_skills(self.user_dir, is_builtin=False)
        for skill in user_skills:
            skill.enabled = self._config.is_enabled(skill.id, default=True)

            if skill.extends:
                # Extend mode: merge with built-in
                if skill.extends in self._skills:
                    base = self._skills[skill.extends]
                    merged = self._merge_skill(base, skill)
                    self._skills[base.id] = merged
                    logger.info(f"User skill '{skill.id}' extends '{skill.extends}'")
                else:
                    # Extending non-existent skill - just add as new skill
                    logger.warning(
                        f"User skill '{skill.id}' extends non-existent skill '{skill.extends}', "
                        "loading as standalone skill"
                    )
                    self._skills[skill.id] = skill
            elif skill.id in self._skills:
                # Override mode: complete replacement (existing behavior)
                logger.info(f"User skill '{skill.id}' overrides built-in")
                self._skills[skill.id] = skill
            else:
                # New skill
                self._skills[skill.id] = skill
                logger.debug(f"Loaded user skill: {skill.id}")

    def reload(self) -> None:
        """Reload all skills from disk."""
        self._load_config()
        self._load_skills()

    def get(self, skill_id: str) -> Skill | None:
        """Get a skill by ID.

        Args:
            skill_id: The skill identifier

        Returns:
            The skill or None if not found
        """
        return self._skills.get(skill_id)

    def list_skills(self) -> list[Skill]:
        """List all registered skills.

        Returns:
            List of all skills (both enabled and disabled)
        """
        return list(self._skills.values())

    def list_enabled_skills(self) -> list[Skill]:
        """List only enabled skills.

        Returns:
            List of enabled skills
        """
        return [s for s in self._skills.values() if s.enabled]

    def enable(self, skill_id: str) -> bool:
        """Enable a skill.

        Args:
            skill_id: The skill identifier

        Returns:
            True if the skill was found and enabled
        """
        skill = self._skills.get(skill_id)
        if skill is None:
            return False

        skill.enabled = True
        self._config.set_enabled(skill_id, True)
        self._save_config()
        return True

    def disable(self, skill_id: str) -> bool:
        """Disable a skill.

        Args:
            skill_id: The skill identifier

        Returns:
            True if the skill was found and disabled
        """
        skill = self._skills.get(skill_id)
        if skill is None:
            return False

        skill.enabled = False
        self._config.set_enabled(skill_id, False)
        self._save_config()
        return True

    def get_all_tool_schemas(self, task_registry: TaskRegistry) -> list[dict[str, Any]]:
        """Get tool schemas for all enabled skills.

        Args:
            task_registry: Registry of available tasks.

        Returns:
            List of tool schemas (deduplicated by name).
        """
        schemas: list[dict[str, Any]] = []
        seen: set[str] = set()

        for skill in self.list_enabled_skills():
            for schema in skill.get_tool_schemas(task_registry):
                name = schema.get("name", "")
                if name and name not in seen:
                    schemas.append(schema)
                    seen.add(name)

        return schemas

    def format_for_prompt(self, task_registry: TaskRegistry | None = None) -> str:
        """Format all enabled skills for the agent's system prompt.

        Args:
            task_registry: Optional registry to pass to skill formatting.

        Returns:
            Formatted skills section for the system prompt
        """
        enabled = self.list_enabled_skills()
        if not enabled:
            return ""

        lines = ["\n## Available Skills\n"]
        lines.append("The following skills provide guidance for handling specific requests:\n")

        for skill in sorted(enabled, key=lambda s: s.name):
            lines.append(skill.format_for_prompt(task_registry))
            lines.append("")  # Blank line between skills

        return "\n".join(lines)

    def __len__(self) -> int:
        return len(self._skills)

    def __iter__(self):
        return iter(self._skills.values())


# Default registry instance (lazy-loaded)
_default_registry: SkillsRegistry | None = None


def get_default_registry() -> SkillsRegistry:
    """Get the default skills registry instance.

    Returns:
        The default SkillsRegistry (lazily created)
    """
    global _default_registry
    if _default_registry is None:
        _default_registry = SkillsRegistry()
    return _default_registry
