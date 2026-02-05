"""Skills system for Son of Simon.

Skills provide declarative guidance that improves agent reliability
through examples, safe defaults, and behavior rules.

Key distinction:
- Tools = Batteries-included macOS automation (Mail, Calendar, etc.)
- Skills = Declarative guidance that improves reliability
"""

from macbot.skills.loader import load_skill, load_skill_from_string
from macbot.skills.models import Skill, SkillsConfig
from macbot.skills.registry import SkillsRegistry

__all__ = [
    "Skill",
    "SkillsConfig",
    "SkillsRegistry",
    "load_skill",
    "load_skill_from_string",
]
