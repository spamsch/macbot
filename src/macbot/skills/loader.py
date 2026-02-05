"""Loader for SKILL.md files with YAML frontmatter."""

import logging
import re
from pathlib import Path
from typing import Any

import yaml

from macbot.skills.models import Skill

logger = logging.getLogger(__name__)

# Pattern to match YAML frontmatter (--- at start and end)
FRONTMATTER_PATTERN = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n?(.*)",
    re.DOTALL,
)


def parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from markdown content.

    Args:
        content: The full file content

    Returns:
        Tuple of (frontmatter_dict, body_text)

    Raises:
        ValueError: If frontmatter is malformed
    """
    match = FRONTMATTER_PATTERN.match(content)
    if not match:
        raise ValueError("No YAML frontmatter found (must start with ---)")

    yaml_content = match.group(1)
    body = match.group(2) or ""

    try:
        frontmatter = yaml.safe_load(yaml_content)
        if not isinstance(frontmatter, dict):
            raise ValueError("Frontmatter must be a YAML dictionary")
        return frontmatter, body.strip()
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in frontmatter: {e}") from e


def load_skill_from_string(
    content: str,
    source_path: Path | None = None,
    is_builtin: bool = False,
) -> Skill:
    """Load a skill from a SKILL.md string content.

    Args:
        content: The SKILL.md file content
        source_path: Optional path for error messages
        is_builtin: Whether this is a built-in skill

    Returns:
        Parsed Skill object

    Raises:
        ValueError: If the content is invalid
    """
    frontmatter, body = parse_frontmatter(content)

    # Required fields
    if "id" not in frontmatter:
        raise ValueError("Skill must have an 'id' field")
    if "name" not in frontmatter:
        raise ValueError("Skill must have a 'name' field")
    if "description" not in frontmatter:
        raise ValueError("Skill must have a 'description' field")

    # Normalize list fields
    def ensure_list(value: Any) -> list:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return value
        return [str(value)]

    # Build skill from frontmatter
    return Skill(
        id=frontmatter["id"],
        name=frontmatter["name"],
        description=frontmatter["description"],
        apps=ensure_list(frontmatter.get("apps")),
        tasks=ensure_list(frontmatter.get("tasks")),
        examples=ensure_list(frontmatter.get("examples")),
        safe_defaults=frontmatter.get("safe_defaults") or {},
        confirm_before_write=ensure_list(frontmatter.get("confirm_before_write")),
        requires_permissions=ensure_list(frontmatter.get("requires_permissions")),
        body=body,
        extends=frontmatter.get("extends"),
        source_path=source_path,
        is_builtin=is_builtin,
        enabled=True,  # Default to enabled; registry will apply config
    )


def load_skill(skill_path: Path, is_builtin: bool = False) -> Skill:
    """Load a skill from a SKILL.md file.

    Args:
        skill_path: Path to the SKILL.md file
        is_builtin: Whether this is a built-in skill

    Returns:
        Parsed Skill object

    Raises:
        FileNotFoundError: If the file doesn't exist
        ValueError: If the file content is invalid
    """
    if not skill_path.exists():
        raise FileNotFoundError(f"Skill file not found: {skill_path}")

    content = skill_path.read_text(encoding="utf-8")
    return load_skill_from_string(content, source_path=skill_path, is_builtin=is_builtin)


def discover_skills(directory: Path, is_builtin: bool = False) -> list[Skill]:
    """Discover all skills in a directory.

    Looks for directories containing SKILL.md files.

    Args:
        directory: Root directory to search
        is_builtin: Whether these are built-in skills

    Returns:
        List of loaded skills (malformed skills are skipped with warning)
    """
    skills = []

    if not directory.exists():
        return skills

    # Look for SKILL.md files in subdirectories
    for skill_dir in directory.iterdir():
        if not skill_dir.is_dir():
            continue

        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue

        try:
            skill = load_skill(skill_file, is_builtin=is_builtin)
            skills.append(skill)
            logger.debug(f"Loaded skill: {skill.id} from {skill_file}")
        except Exception as e:
            logger.warning(f"Skipping malformed skill at {skill_file}: {e}")

    return skills
