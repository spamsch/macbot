"""Skill enrichment system.

Enriches bare skills (e.g. from ClawHub) with tasks, examples, and behavior
notes by making a single LLM call with the full task catalog and example skills.
"""

import logging
import re
from pathlib import Path

from macbot.skills.loader import load_skill_from_string, parse_frontmatter
from macbot.skills.models import Skill

logger = logging.getLogger(__name__)


def is_enriched(skill: Skill) -> bool:
    """Check whether a skill has already been enriched."""
    return skill.metadata.get("enriched", False) is True


def build_task_catalog() -> str:
    """Build a compact catalog of all available task names and descriptions."""
    from macbot.tasks import create_default_registry

    registry = create_default_registry()
    lines = []
    for task in registry.list_tasks():
        lines.append(f"- {task.name}: {task.description}")
    return "\n".join(sorted(lines))


def _load_example_skills() -> list[str]:
    """Load 2 built-in skills as few-shot examples."""
    skills_dir = Path(__file__).resolve().parent.parent.parent.parent / "skills"
    examples = []
    for name in ("mail_assistant", "safari_assistant"):
        path = skills_dir / name / "SKILL.md"
        if path.exists():
            examples.append(path.read_text(encoding="utf-8"))
    return examples


def build_enrichment_prompt(
    skill: Skill,
    task_catalog: str,
    example_skills: list[str],
) -> list[dict[str, str]]:
    """Build LLM messages for the enrichment call."""
    examples_text = "\n\n---\n\n".join(
        f"### Example {i + 1}\n```\n{ex}\n```"
        for i, ex in enumerate(example_skills)
    )

    system = f"""\
You write Son of Simon SKILL.md files. A SKILL.md has YAML frontmatter \
(between --- delimiters) and a markdown body with behavior notes.

Given a bare skill that only has basic metadata, enrich it by adding:
1. `tasks:` — list of task names this skill should use (from the catalog below)
2. `examples:` — 5-8 natural language prompts a user might say
3. `enriched: true` in the frontmatter (as a top-level field)
4. A markdown body with ## Behavior Notes containing practical guidance

## Rules
- Only reference task names that exist in the catalog below
- Preserve ALL existing frontmatter fields (id, name, description, etc.)
- Output ONLY the complete SKILL.md content (frontmatter + body), nothing else
- Do NOT wrap the output in code fences
- Keep the style consistent with the examples below

## Available Tasks
{task_catalog}

## Example Enriched Skills
{examples_text}"""

    # Read the raw SKILL.md content if available
    if skill.source_path and skill.source_path.exists():
        bare_content = skill.source_path.read_text(encoding="utf-8")
    else:
        # Reconstruct minimal content from skill fields
        bare_content = f"---\nid: {skill.id}\nname: {skill.name}\ndescription: {skill.description}\n---\n"

    user = f"Enrich this skill:\n\n{bare_content}"

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def parse_enriched_output(llm_output: str) -> str:
    """Strip code fences and validate the enriched SKILL.md content."""
    text = llm_output.strip()

    # Strip code fences if present
    text = re.sub(r"^```(?:markdown|yaml|md)?\s*\n", "", text)
    text = re.sub(r"\n```\s*$", "", text)
    text = text.strip()

    # Validate frontmatter parses correctly
    parse_frontmatter(text)
    return text


async def enrich_skill(skill: Skill, force: bool = False) -> Skill:
    """Enrich a bare skill with tasks, examples, and behavior notes.

    Makes a single LLM call using the configured provider to rewrite the
    skill's SKILL.md with full guidance content.

    Args:
        skill: The skill to enrich.
        force: If True, re-enrich even if already enriched.

    Returns:
        The enriched Skill object (also written to disk).

    Raises:
        ValueError: If the skill has no source_path or enrichment fails.
    """
    if is_enriched(skill) and not force:
        logger.info("Skill '%s' is already enriched, skipping", skill.id)
        return skill

    if not skill.source_path:
        raise ValueError(
            f"Skill '{skill.id}' has no source_path — cannot enrich a built-in "
            "skill without a file on disk"
        )

    # Build the prompt
    task_catalog = build_task_catalog()
    example_skills = _load_example_skills()
    messages = build_enrichment_prompt(skill, task_catalog, example_skills)

    # Create a provider (same pattern as Agent._create_provider)
    from macbot.config import settings
    from macbot.providers.base import Message
    from macbot.providers.litellm_provider import LiteLLMProvider

    model = settings.get_model()
    api_key = settings.get_api_key_for_model(model)
    provider = LiteLLMProvider(model=model, api_key=api_key)

    # Single LLM call (no tools, no streaming)
    response = await provider.chat(
        messages=[Message(role=m["role"], content=m["content"]) for m in messages],
    )

    if not response.content:
        raise ValueError("LLM returned empty response during enrichment")

    # Parse and validate
    enriched_content = parse_enriched_output(response.content)

    # Write back to disk
    skill.source_path.write_text(enriched_content, encoding="utf-8")
    logger.info("Wrote enriched SKILL.md to %s", skill.source_path)

    # Reload and return
    return load_skill_from_string(
        enriched_content,
        source_path=skill.source_path,
        is_builtin=skill.is_builtin,
    )
