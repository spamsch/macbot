"""Tests for the Skills system."""

import json
import tempfile
from pathlib import Path

import pytest

from macbot.skills.loader import load_skill, load_skill_from_string, parse_frontmatter
from macbot.skills.models import Skill, SkillsConfig
from macbot.skills.registry import SkillsRegistry, get_builtin_skills_dir
from macbot.tasks import create_default_registry


class TestParseFrontmatter:
    """Tests for YAML frontmatter parsing."""

    def test_parse_valid_frontmatter(self) -> None:
        """Test parsing valid frontmatter."""
        content = """---
id: test_skill
name: Test Skill
description: A test skill
---

This is the body."""

        frontmatter, body = parse_frontmatter(content)

        assert frontmatter["id"] == "test_skill"
        assert frontmatter["name"] == "Test Skill"
        assert frontmatter["description"] == "A test skill"
        assert body == "This is the body."

    def test_parse_frontmatter_with_lists(self) -> None:
        """Test parsing frontmatter with list values."""
        content = """---
id: test
name: Test
description: Test
apps:
  - Mail
  - Calendar
examples:
  - "Example one"
  - "Example two"
---
Body text."""

        frontmatter, body = parse_frontmatter(content)

        assert frontmatter["apps"] == ["Mail", "Calendar"]
        assert frontmatter["examples"] == ["Example one", "Example two"]

    def test_parse_frontmatter_with_dict(self) -> None:
        """Test parsing frontmatter with dict values."""
        content = """---
id: test
name: Test
description: Test
safe_defaults:
  days: 7
  limit: 20
---
"""
        frontmatter, body = parse_frontmatter(content)

        assert frontmatter["safe_defaults"] == {"days": 7, "limit": 20}

    def test_parse_missing_frontmatter(self) -> None:
        """Test that missing frontmatter raises ValueError."""
        content = "Just some text without frontmatter."

        with pytest.raises(ValueError, match="No YAML frontmatter"):
            parse_frontmatter(content)

    def test_parse_invalid_yaml(self) -> None:
        """Test that invalid YAML raises ValueError."""
        content = """---
id: test
invalid: yaml: here: broken
---
"""
        with pytest.raises(ValueError, match="Invalid YAML"):
            parse_frontmatter(content)


class TestLoadSkillFromString:
    """Tests for loading skills from string content."""

    def test_load_minimal_skill(self) -> None:
        """Test loading a skill with minimal required fields."""
        content = """---
id: test_skill
name: Test Skill
description: A minimal test skill
---
"""
        skill = load_skill_from_string(content)

        assert skill.id == "test_skill"
        assert skill.name == "Test Skill"
        assert skill.description == "A minimal test skill"
        assert skill.enabled is True
        assert skill.apps == []
        assert skill.examples == []

    def test_load_full_skill(self) -> None:
        """Test loading a skill with all fields populated."""
        content = """---
id: mail_assistant
name: Mail Assistant
description: Email management skill
apps:
  - Mail
tasks:
  - search_emails
  - send_email
examples:
  - "Check my emails"
  - "Send an email to John"
safe_defaults:
  days: 7
  limit: 20
confirm_before_write:
  - send email
  - delete email
requires_permissions:
  - Automation:Mail
---

## Behavior Notes

Always confirm before sending.
"""
        skill = load_skill_from_string(content)

        assert skill.id == "mail_assistant"
        assert skill.apps == ["Mail"]
        assert skill.tasks == ["search_emails", "send_email"]
        assert len(skill.examples) == 2
        assert skill.safe_defaults == {"days": 7, "limit": 20}
        assert skill.confirm_before_write == ["send email", "delete email"]
        assert skill.requires_permissions == ["Automation:Mail"]
        assert "Always confirm before sending" in skill.body

    def test_load_missing_id(self) -> None:
        """Test that missing id raises ValueError."""
        content = """---
name: Test
description: Test
---
"""
        with pytest.raises(ValueError, match="must have an 'id' field"):
            load_skill_from_string(content)

    def test_load_missing_name(self) -> None:
        """Test that missing name raises ValueError."""
        content = """---
id: test
description: Test
---
"""
        with pytest.raises(ValueError, match="must have a 'name' field"):
            load_skill_from_string(content)

    def test_load_missing_description(self) -> None:
        """Test that missing description raises ValueError."""
        content = """---
id: test
name: Test
---
"""
        with pytest.raises(ValueError, match="must have a 'description' field"):
            load_skill_from_string(content)

    def test_single_value_converted_to_list(self) -> None:
        """Test that single values are converted to lists."""
        content = """---
id: test
name: Test
description: Test
apps: Mail
examples: "Check email"
---
"""
        skill = load_skill_from_string(content)

        assert skill.apps == ["Mail"]
        assert skill.examples == ["Check email"]


class TestLoadSkill:
    """Tests for loading skills from files."""

    def test_load_skill_from_file(self, tmp_path: Path) -> None:
        """Test loading a skill from a file."""
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text("""---
id: file_skill
name: File Skill
description: Loaded from file
---
Body content.
""")
        skill = load_skill(skill_file)

        assert skill.id == "file_skill"
        assert skill.source_path == skill_file

    def test_load_skill_not_found(self, tmp_path: Path) -> None:
        """Test that FileNotFoundError is raised for missing file."""
        with pytest.raises(FileNotFoundError):
            load_skill(tmp_path / "nonexistent.md")

    def test_load_builtin_skill(self, tmp_path: Path) -> None:
        """Test loading a skill with is_builtin flag."""
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text("""---
id: builtin_skill
name: Built-in
description: A built-in skill
---
""")
        skill = load_skill(skill_file, is_builtin=True)

        assert skill.is_builtin is True


class TestSkillsConfig:
    """Tests for SkillsConfig."""

    def test_is_enabled_default(self) -> None:
        """Test default enabled state."""
        config = SkillsConfig()

        assert config.is_enabled("unknown_skill") is True
        assert config.is_enabled("unknown_skill", default=False) is False

    def test_set_enabled(self) -> None:
        """Test setting enabled state."""
        config = SkillsConfig()

        config.set_enabled("skill1", True)
        config.set_enabled("skill2", False)

        assert config.is_enabled("skill1") is True
        assert config.is_enabled("skill2") is False


class TestSkillsRegistry:
    """Tests for SkillsRegistry."""

    def test_registry_loads_builtin_skills(self, tmp_path: Path) -> None:
        """Test that registry loads built-in skills."""
        # Create built-in skills directory
        builtin_dir = tmp_path / "builtin"
        skill_dir = builtin_dir / "test_skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("""---
id: test_skill
name: Test Skill
description: A test skill
---
""")
        registry = SkillsRegistry(
            builtin_dir=builtin_dir,
            user_dir=tmp_path / "user",
            config_file=tmp_path / "config.json",
        )

        assert len(registry) == 1
        skill = registry.get("test_skill")
        assert skill is not None
        assert skill.is_builtin is True

    def test_registry_user_overrides_builtin(self, tmp_path: Path) -> None:
        """Test that user skills override built-in skills."""
        # Create built-in skill
        builtin_dir = tmp_path / "builtin"
        builtin_skill_dir = builtin_dir / "test_skill"
        builtin_skill_dir.mkdir(parents=True)
        (builtin_skill_dir / "SKILL.md").write_text("""---
id: test_skill
name: Built-in Test
description: Original built-in
---
""")
        # Create user override
        user_dir = tmp_path / "user"
        user_skill_dir = user_dir / "test_skill"
        user_skill_dir.mkdir(parents=True)
        (user_skill_dir / "SKILL.md").write_text("""---
id: test_skill
name: User Test
description: User override
---
""")
        registry = SkillsRegistry(
            builtin_dir=builtin_dir,
            user_dir=user_dir,
            config_file=tmp_path / "config.json",
        )

        skill = registry.get("test_skill")
        assert skill is not None
        assert skill.name == "User Test"
        assert skill.is_builtin is False

    def test_registry_enable_disable(self, tmp_path: Path) -> None:
        """Test enabling and disabling skills."""
        # Create skill
        builtin_dir = tmp_path / "builtin"
        skill_dir = builtin_dir / "test_skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("""---
id: test_skill
name: Test
description: Test
---
""")
        config_file = tmp_path / "config.json"
        registry = SkillsRegistry(
            builtin_dir=builtin_dir,
            user_dir=tmp_path / "user",
            config_file=config_file,
        )

        # Disable skill
        assert registry.disable("test_skill") is True
        skill = registry.get("test_skill")
        assert skill is not None
        assert skill.enabled is False

        # Check config was persisted
        assert config_file.exists()
        saved_config = json.loads(config_file.read_text())
        assert saved_config["enabled_skills"]["test_skill"] is False

        # Enable skill
        assert registry.enable("test_skill") is True
        skill = registry.get("test_skill")
        assert skill is not None
        assert skill.enabled is True

    def test_registry_list_enabled_skills(self, tmp_path: Path) -> None:
        """Test listing only enabled skills."""
        builtin_dir = tmp_path / "builtin"

        for name, enabled in [("skill1", True), ("skill2", False), ("skill3", True)]:
            skill_dir = builtin_dir / name
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(f"""---
id: {name}
name: {name}
description: Test
---
""")
        # Pre-create config
        config_file = tmp_path / "config.json"
        config_file.write_text('{"enabled_skills": {"skill2": false}}')

        registry = SkillsRegistry(
            builtin_dir=builtin_dir,
            user_dir=tmp_path / "user",
            config_file=config_file,
        )

        enabled = registry.list_enabled_skills()
        enabled_ids = {s.id for s in enabled}

        assert "skill1" in enabled_ids
        assert "skill2" not in enabled_ids
        assert "skill3" in enabled_ids

    def test_registry_skips_malformed_skills(self, tmp_path: Path) -> None:
        """Test that malformed skills are skipped without crashing."""
        builtin_dir = tmp_path / "builtin"

        # Valid skill
        valid_dir = builtin_dir / "valid"
        valid_dir.mkdir(parents=True)
        (valid_dir / "SKILL.md").write_text("""---
id: valid
name: Valid
description: Valid skill
---
""")
        # Malformed skill (missing id)
        malformed_dir = builtin_dir / "malformed"
        malformed_dir.mkdir(parents=True)
        (malformed_dir / "SKILL.md").write_text("""---
name: Malformed
description: Missing id
---
""")
        registry = SkillsRegistry(
            builtin_dir=builtin_dir,
            user_dir=tmp_path / "user",
            config_file=tmp_path / "config.json",
        )

        # Should load only the valid skill
        assert len(registry) == 1
        assert registry.get("valid") is not None

    def test_registry_enable_nonexistent_skill(self, tmp_path: Path) -> None:
        """Test enabling a nonexistent skill returns False."""
        registry = SkillsRegistry(
            builtin_dir=tmp_path / "builtin",
            user_dir=tmp_path / "user",
            config_file=tmp_path / "config.json",
        )

        assert registry.enable("nonexistent") is False
        assert registry.disable("nonexistent") is False


class TestSkillFormatForPrompt:
    """Tests for formatting skills for the system prompt."""

    def test_format_minimal(self) -> None:
        """Test formatting a minimal skill."""
        skill = Skill(
            id="test",
            name="Test Skill",
            description="A test skill",
        )

        formatted = skill.format_for_prompt()

        assert "### Test Skill" in formatted
        assert "A test skill" in formatted

    def test_format_with_examples(self) -> None:
        """Test formatting with examples."""
        skill = Skill(
            id="test",
            name="Test",
            description="Test",
            examples=["Example 1", "Example 2"],
        )

        formatted = skill.format_for_prompt()

        assert "**Examples:**" in formatted
        assert '"Example 1"' in formatted
        assert '"Example 2"' in formatted

    def test_format_with_defaults(self) -> None:
        """Test formatting with safe defaults."""
        skill = Skill(
            id="test",
            name="Test",
            description="Test",
            safe_defaults={"days": 7, "limit": 20},
        )

        formatted = skill.format_for_prompt()

        assert "**Defaults:**" in formatted
        assert "days=7" in formatted
        assert "limit=20" in formatted

    def test_format_with_confirm(self) -> None:
        """Test formatting with confirmation rules."""
        skill = Skill(
            id="test",
            name="Test",
            description="Test",
            confirm_before_write=["delete", "send"],
        )

        formatted = skill.format_for_prompt()

        assert "**Important:**" in formatted
        assert "delete" in formatted
        assert "send" in formatted

    def test_format_with_body(self) -> None:
        """Test formatting with body content."""
        skill = Skill(
            id="test",
            name="Test",
            description="Test",
            body="## Notes\n\nAlways be careful.",
        )

        formatted = skill.format_for_prompt()

        assert "## Notes" in formatted
        assert "Always be careful." in formatted


class TestRegistryFormatForPrompt:
    """Tests for formatting registry skills for system prompt."""

    def test_format_enabled_skills_only(self, tmp_path: Path) -> None:
        """Test that only enabled skills are included in prompt."""
        builtin_dir = tmp_path / "builtin"

        for name in ["enabled", "disabled"]:
            skill_dir = builtin_dir / name
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(f"""---
id: {name}
name: {name.title()}
description: {name} skill
---
""")
        config_file = tmp_path / "config.json"
        config_file.write_text('{"enabled_skills": {"disabled": false}}')

        registry = SkillsRegistry(
            builtin_dir=builtin_dir,
            user_dir=tmp_path / "user",
            config_file=config_file,
        )

        formatted = registry.format_for_prompt()

        assert "Enabled" in formatted
        assert "Disabled" not in formatted

    def test_format_empty_registry(self, tmp_path: Path) -> None:
        """Test formatting an empty registry."""
        registry = SkillsRegistry(
            builtin_dir=tmp_path / "builtin",
            user_dir=tmp_path / "user",
            config_file=tmp_path / "config.json",
        )

        formatted = registry.format_for_prompt()

        assert formatted == ""

    def test_format_includes_tools(self, tmp_path: Path) -> None:
        """Test that formatted skills include tool list."""
        builtin_dir = tmp_path / "builtin"
        skill_dir = builtin_dir / "test"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("""---
id: test
name: Test Skill
description: A test skill
tasks:
  - task_one
  - task_two
---
""")
        registry = SkillsRegistry(
            builtin_dir=builtin_dir,
            user_dir=tmp_path / "user",
            config_file=tmp_path / "config.json",
        )

        formatted = registry.format_for_prompt()

        assert "**Tools:**" in formatted
        assert "task_one" in formatted
        assert "task_two" in formatted


class TestSkillTaskValidation:
    """Verify all built-in skills reference actually existing tasks."""

    @pytest.fixture
    def task_registry(self):
        """Create a task registry with all default tasks."""
        return create_default_registry()

    @pytest.fixture
    def skills_registry(self):
        """Create a skills registry with built-in skills."""
        builtin_dir = get_builtin_skills_dir()
        return SkillsRegistry(
            builtin_dir=builtin_dir,
            user_dir=Path("/nonexistent"),  # No user skills
            config_file=Path("/tmp/test_skills_config.json"),
        )

    def test_mail_assistant_tasks_exist(self, task_registry, skills_registry) -> None:
        """Verify mail_assistant references real tasks."""
        skill = skills_registry.get("mail_assistant")
        if skill is None:
            pytest.skip("mail_assistant skill not found")

        for task_name in skill.tasks:
            task = task_registry.get(task_name)
            assert task is not None, f"Task '{task_name}' not found in registry"

    def test_calendar_assistant_tasks_exist(self, task_registry, skills_registry) -> None:
        """Verify calendar_assistant references real tasks."""
        skill = skills_registry.get("calendar_assistant")
        if skill is None:
            pytest.skip("calendar_assistant skill not found")

        for task_name in skill.tasks:
            task = task_registry.get(task_name)
            assert task is not None, f"Task '{task_name}' not found in registry"

    def test_reminders_assistant_tasks_exist(self, task_registry, skills_registry) -> None:
        """Verify reminders_assistant references real tasks."""
        skill = skills_registry.get("reminders_assistant")
        if skill is None:
            pytest.skip("reminders_assistant skill not found")

        for task_name in skill.tasks:
            task = task_registry.get(task_name)
            assert task is not None, f"Task '{task_name}' not found in registry"

    def test_notes_assistant_tasks_exist(self, task_registry, skills_registry) -> None:
        """Verify notes_assistant references real tasks."""
        skill = skills_registry.get("notes_assistant")
        if skill is None:
            pytest.skip("notes_assistant skill not found")

        for task_name in skill.tasks:
            task = task_registry.get(task_name)
            assert task is not None, f"Task '{task_name}' not found in registry"

    def test_safari_assistant_tasks_exist(self, task_registry, skills_registry) -> None:
        """Verify safari_assistant references real tasks."""
        skill = skills_registry.get("safari_assistant")
        if skill is None:
            pytest.skip("safari_assistant skill not found")

        for task_name in skill.tasks:
            task = task_registry.get(task_name)
            assert task is not None, f"Task '{task_name}' not found in registry"

    def test_browser_automation_tasks_exist(self, task_registry, skills_registry) -> None:
        """Verify browser_automation references real tasks."""
        skill = skills_registry.get("browser_automation")
        if skill is None:
            pytest.skip("browser_automation skill not found")

        for task_name in skill.tasks:
            task = task_registry.get(task_name)
            assert task is not None, f"Task '{task_name}' not found in registry"

    def test_all_builtin_skills_have_valid_tasks(self, task_registry, skills_registry) -> None:
        """Verify all built-in skills reference only existing tasks."""
        for skill in skills_registry.list_skills():
            if not skill.is_builtin:
                continue
            for task_name in skill.tasks:
                task = task_registry.get(task_name)
                assert task is not None, (
                    f"Skill '{skill.id}' references non-existent task '{task_name}'"
                )


class TestSkillExtends:
    """Test the extends/merge mechanism."""

    def test_extend_appends_examples(self, tmp_path: Path) -> None:
        """User skill with extends appends examples to base."""
        # Create base skill
        builtin_dir = tmp_path / "builtin"
        base_dir = builtin_dir / "base_skill"
        base_dir.mkdir(parents=True)
        (base_dir / "SKILL.md").write_text("""---
id: base_skill
name: Base Skill
description: The base skill
examples:
  - "Base example 1"
  - "Base example 2"
---
""")
        # Create extension skill
        user_dir = tmp_path / "user"
        ext_dir = user_dir / "my_extension"
        ext_dir.mkdir(parents=True)
        (ext_dir / "SKILL.md").write_text("""---
id: my_extension
extends: base_skill
name: my_extension
description: Extension
examples:
  - "New example 1"
---
""")
        registry = SkillsRegistry(
            builtin_dir=builtin_dir,
            user_dir=user_dir,
            config_file=tmp_path / "config.json",
        )

        # The base skill should have merged examples
        skill = registry.get("base_skill")
        assert skill is not None
        assert len(skill.examples) == 3
        assert "Base example 1" in skill.examples
        assert "Base example 2" in skill.examples
        assert "New example 1" in skill.examples

    def test_extend_appends_tasks(self, tmp_path: Path) -> None:
        """User skill with extends appends tasks to base."""
        builtin_dir = tmp_path / "builtin"
        base_dir = builtin_dir / "base_skill"
        base_dir.mkdir(parents=True)
        (base_dir / "SKILL.md").write_text("""---
id: base_skill
name: Base Skill
description: The base skill
tasks:
  - task_a
  - task_b
---
""")
        user_dir = tmp_path / "user"
        ext_dir = user_dir / "my_extension"
        ext_dir.mkdir(parents=True)
        (ext_dir / "SKILL.md").write_text("""---
id: my_extension
extends: base_skill
name: my_extension
description: Extension
tasks:
  - task_c
  - task_a
---
""")
        registry = SkillsRegistry(
            builtin_dir=builtin_dir,
            user_dir=user_dir,
            config_file=tmp_path / "config.json",
        )

        skill = registry.get("base_skill")
        assert skill is not None
        # Should have all tasks, deduplicated
        assert skill.tasks == ["task_a", "task_b", "task_c"]

    def test_extend_merges_defaults(self, tmp_path: Path) -> None:
        """Extension safe_defaults merge with base, extension wins on conflict."""
        builtin_dir = tmp_path / "builtin"
        base_dir = builtin_dir / "base_skill"
        base_dir.mkdir(parents=True)
        (base_dir / "SKILL.md").write_text("""---
id: base_skill
name: Base Skill
description: The base skill
safe_defaults:
  days: 7
  limit: 20
---
""")
        user_dir = tmp_path / "user"
        ext_dir = user_dir / "my_extension"
        ext_dir.mkdir(parents=True)
        (ext_dir / "SKILL.md").write_text("""---
id: my_extension
extends: base_skill
name: my_extension
description: Extension
safe_defaults:
  limit: 50
  new_key: value
---
""")
        registry = SkillsRegistry(
            builtin_dir=builtin_dir,
            user_dir=user_dir,
            config_file=tmp_path / "config.json",
        )

        skill = registry.get("base_skill")
        assert skill is not None
        assert skill.safe_defaults == {"days": 7, "limit": 50, "new_key": "value"}

    def test_extend_replaces_body_when_provided(self, tmp_path: Path) -> None:
        """User skill body replaces base body when non-empty."""
        builtin_dir = tmp_path / "builtin"
        base_dir = builtin_dir / "base_skill"
        base_dir.mkdir(parents=True)
        (base_dir / "SKILL.md").write_text("""---
id: base_skill
name: Base Skill
description: The base skill
---
Base body content.
""")
        user_dir = tmp_path / "user"
        ext_dir = user_dir / "my_extension"
        ext_dir.mkdir(parents=True)
        (ext_dir / "SKILL.md").write_text("""---
id: my_extension
extends: base_skill
name: my_extension
description: Extension
---
New body content from extension.
""")
        registry = SkillsRegistry(
            builtin_dir=builtin_dir,
            user_dir=user_dir,
            config_file=tmp_path / "config.json",
        )

        skill = registry.get("base_skill")
        assert skill is not None
        assert "New body content from extension" in skill.body
        assert "Base body content" not in skill.body

    def test_extend_keeps_base_body_when_empty(self, tmp_path: Path) -> None:
        """Base body kept when extension body is empty."""
        builtin_dir = tmp_path / "builtin"
        base_dir = builtin_dir / "base_skill"
        base_dir.mkdir(parents=True)
        (base_dir / "SKILL.md").write_text("""---
id: base_skill
name: Base Skill
description: The base skill
---
Base body content.
""")
        user_dir = tmp_path / "user"
        ext_dir = user_dir / "my_extension"
        ext_dir.mkdir(parents=True)
        (ext_dir / "SKILL.md").write_text("""---
id: my_extension
extends: base_skill
name: my_extension
description: Extension
examples:
  - "New example"
---
""")
        registry = SkillsRegistry(
            builtin_dir=builtin_dir,
            user_dir=user_dir,
            config_file=tmp_path / "config.json",
        )

        skill = registry.get("base_skill")
        assert skill is not None
        assert "Base body content" in skill.body

    def test_extend_nonexistent_skill_loads_standalone(self, tmp_path: Path) -> None:
        """Extending a non-existent skill loads skill as standalone."""
        builtin_dir = tmp_path / "builtin"
        builtin_dir.mkdir(parents=True)

        user_dir = tmp_path / "user"
        ext_dir = user_dir / "orphan_extension"
        ext_dir.mkdir(parents=True)
        (ext_dir / "SKILL.md").write_text("""---
id: orphan_extension
extends: nonexistent_skill
name: Orphan Extension
description: Extends a skill that doesn't exist
---
""")
        registry = SkillsRegistry(
            builtin_dir=builtin_dir,
            user_dir=user_dir,
            config_file=tmp_path / "config.json",
        )

        # Should load as standalone skill
        skill = registry.get("orphan_extension")
        assert skill is not None
        assert skill.name == "Orphan Extension"

    def test_extend_preserves_base_id(self, tmp_path: Path) -> None:
        """Merged skill keeps the base skill's ID."""
        builtin_dir = tmp_path / "builtin"
        base_dir = builtin_dir / "base_skill"
        base_dir.mkdir(parents=True)
        (base_dir / "SKILL.md").write_text("""---
id: base_skill
name: Base Skill
description: The base skill
---
""")
        user_dir = tmp_path / "user"
        ext_dir = user_dir / "my_extension"
        ext_dir.mkdir(parents=True)
        (ext_dir / "SKILL.md").write_text("""---
id: my_extension
extends: base_skill
name: Extended Base
description: Extended description
---
""")
        registry = SkillsRegistry(
            builtin_dir=builtin_dir,
            user_dir=user_dir,
            config_file=tmp_path / "config.json",
        )

        # Should be accessible by base ID
        skill = registry.get("base_skill")
        assert skill is not None
        assert skill.name == "Extended Base"

        # Extension ID should not exist separately
        assert registry.get("my_extension") is None


class TestSkillToolSchemas:
    """Test tool schema retrieval from skills."""

    def test_get_tool_schemas(self) -> None:
        """Test getting tool schemas for a skill."""
        task_registry = create_default_registry()

        skill = Skill(
            id="test",
            name="Test",
            description="Test",
            tasks=["get_system_info", "get_current_time"],
        )

        schemas = skill.get_tool_schemas(task_registry)

        assert len(schemas) == 2
        names = [s["name"] for s in schemas]
        assert "get_system_info" in names
        assert "get_current_time" in names

    def test_get_tool_schemas_ignores_missing(self) -> None:
        """Test that missing tasks are silently ignored."""
        task_registry = create_default_registry()

        skill = Skill(
            id="test",
            name="Test",
            description="Test",
            tasks=["get_system_info", "nonexistent_task"],
        )

        schemas = skill.get_tool_schemas(task_registry)

        assert len(schemas) == 1
        assert schemas[0]["name"] == "get_system_info"

    def test_registry_get_all_tool_schemas(self, tmp_path: Path) -> None:
        """Test getting all tool schemas from enabled skills."""
        task_registry = create_default_registry()

        builtin_dir = tmp_path / "builtin"
        for name, tasks in [
            ("skill1", ["get_system_info"]),
            ("skill2", ["get_current_time", "get_system_info"]),  # Duplicate
        ]:
            skill_dir = builtin_dir / name
            skill_dir.mkdir(parents=True)
            tasks_yaml = "\n".join(f"  - {t}" for t in tasks)
            (skill_dir / "SKILL.md").write_text(f"""---
id: {name}
name: {name}
description: Test
tasks:
{tasks_yaml}
---
""")
        registry = SkillsRegistry(
            builtin_dir=builtin_dir,
            user_dir=tmp_path / "user",
            config_file=tmp_path / "config.json",
        )

        schemas = registry.get_all_tool_schemas(task_registry)

        # Should be deduplicated
        names = [s["name"] for s in schemas]
        assert names.count("get_system_info") == 1
        assert "get_current_time" in names
