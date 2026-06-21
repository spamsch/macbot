"""Tests for the Skills system."""

import json
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

    def test_load_missing_id_and_name(self) -> None:
        """Test that missing both id and name raises ValueError."""
        content = """---
description: Test
---
"""
        with pytest.raises(ValueError, match="must have an 'id' or 'name' field"):
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
        # Malformed skill (missing both id and name)
        malformed_dir = builtin_dir / "malformed"
        malformed_dir.mkdir(parents=True)
        (malformed_dir / "SKILL.md").write_text("""---
description: Missing id and name
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
        """Verify all enabled built-in skills reference only existing tasks."""
        for skill in skills_registry.list_skills():
            if not skill.is_builtin or not skill.enabled:
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


class TestAgentSkillsCompatibility:
    """Tests for AgentSkills standard / OpenClaw SKILL.md compatibility."""

    def test_agentskills_name_only_format(self) -> None:
        """Test loading a skill with only `name` (no `id`), as per AgentSkills spec."""
        content = """---
name: pdf-processing
description: Extract text and tables from PDF files.
---

Use the pdf tool to process documents.
"""
        skill = load_skill_from_string(content)

        assert skill.id == "pdf-processing"
        assert skill.name == "pdf-processing"
        assert skill.description == "Extract text and tables from PDF files."
        assert "Use the pdf tool" in skill.body

    def test_agentskills_id_only_format(self) -> None:
        """Test loading a skill with only `id` (no `name`) uses id as name."""
        content = """---
id: my_skill
description: A skill with only an id field.
---
"""
        skill = load_skill_from_string(content)

        assert skill.id == "my_skill"
        assert skill.name == "my_skill"

    def test_agentskills_allowed_tools(self) -> None:
        """Test that `allowed-tools` is mapped to `tasks`."""
        content = """---
name: git-helper
description: Help with git operations.
allowed-tools: Bash Read Write
---
"""
        skill = load_skill_from_string(content)

        assert skill.tasks == ["Bash", "Read", "Write"]

    def test_agentskills_allowed_tools_does_not_override_tasks(self) -> None:
        """Test that explicit `tasks` take priority over `allowed-tools`."""
        content = """---
id: test
name: Test
description: Test
tasks:
  - search_emails
allowed-tools: Bash Read
---
"""
        skill = load_skill_from_string(content)

        assert skill.tasks == ["search_emails"]

    def test_agentskills_extra_fields_in_metadata(self) -> None:
        """Test that unknown frontmatter fields are stored in metadata."""
        content = """---
name: doc-processor
description: Process documents.
license: Apache-2.0
compatibility: Requires pandoc
homepage: https://example.com/doc-processor
user-invocable: true
---
"""
        skill = load_skill_from_string(content)

        assert skill.metadata["license"] == "Apache-2.0"
        assert skill.metadata["compatibility"] == "Requires pandoc"
        assert skill.metadata["homepage"] == "https://example.com/doc-processor"
        assert skill.metadata["user-invocable"] is True

    def test_agentskills_full_openclaw_style_skill(self) -> None:
        """Test loading a full OpenClaw-style skill."""
        content = """---
name: macos-mail
description: Search, read, and manage Apple Mail.
homepage: https://github.com/example/macos-mail
license: MIT
---

## Usage

Run `osascript` to interact with Apple Mail.

## Examples

- "Show unread emails"
- "Search for emails from John"
"""
        skill = load_skill_from_string(content)

        assert skill.id == "macos-mail"
        assert skill.name == "macos-mail"
        assert skill.metadata["homepage"] == "https://github.com/example/macos-mail"
        assert skill.metadata["license"] == "MIT"
        assert "osascript" in skill.body

    def test_agentskills_skill_in_registry(self, tmp_path: Path) -> None:
        """Test that AgentSkills-format skills load correctly in the registry."""
        user_dir = tmp_path / "user"
        skill_dir = user_dir / "git-helper"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("""---
name: git-helper
description: Help with git operations.
license: MIT
---

Use git commands to manage repositories.
""")
        registry = SkillsRegistry(
            builtin_dir=tmp_path / "builtin",
            user_dir=user_dir,
            config_file=tmp_path / "config.json",
        )

        skill = registry.get("git-helper")
        assert skill is not None
        assert skill.name == "git-helper"
        assert skill.metadata["license"] == "MIT"


class TestEssentialTasks:
    """Tests for the essential_tasks field and compact mode behavior."""

    def test_parse_essential_tasks_present(self) -> None:
        """Test parsing a skill with essential_tasks defined."""
        content = """---
id: test
name: Test
description: Test
tasks:
  - task_a
  - task_b
  - task_c
essential_tasks:
  - task_a
  - task_b
---
"""
        skill = load_skill_from_string(content, is_builtin=True)

        assert skill.essential_tasks == ["task_a", "task_b"]

    def test_parse_essential_tasks_absent(self) -> None:
        """Test that missing essential_tasks defaults to None."""
        content = """---
id: test
name: Test
description: Test
tasks:
  - task_a
---
"""
        skill = load_skill_from_string(content, is_builtin=True)

        assert skill.essential_tasks is None

    def test_parse_essential_tasks_empty_list(self) -> None:
        """Test parsing essential_tasks as an explicit empty list."""
        content = """---
id: test
name: Test
description: Test
tasks:
  - task_a
essential_tasks: []
---
"""
        skill = load_skill_from_string(content, is_builtin=True)

        assert skill.essential_tasks == []

    def test_get_effective_tasks_compact_with_essential(self) -> None:
        """Test get_effective_tasks returns essential_tasks in compact mode."""
        skill = Skill(
            id="test", name="Test", description="Test",
            tasks=["task_a", "task_b", "task_c"],
            essential_tasks=["task_a"],
        )

        assert skill.get_effective_tasks(compact=True) == ["task_a"]

    def test_get_effective_tasks_compact_without_essential(self) -> None:
        """Test get_effective_tasks falls back to tasks when essential_tasks is None."""
        skill = Skill(
            id="test", name="Test", description="Test",
            tasks=["task_a", "task_b"],
            essential_tasks=None,
        )

        assert skill.get_effective_tasks(compact=True) == ["task_a", "task_b"]

    def test_get_effective_tasks_compact_empty_essential(self) -> None:
        """Test get_effective_tasks returns empty list when essential_tasks is []."""
        skill = Skill(
            id="test", name="Test", description="Test",
            tasks=["task_a", "task_b"],
            essential_tasks=[],
        )

        assert skill.get_effective_tasks(compact=True) == []

    def test_get_effective_tasks_non_compact(self) -> None:
        """Test get_effective_tasks always returns full tasks when not compact."""
        skill = Skill(
            id="test", name="Test", description="Test",
            tasks=["task_a", "task_b", "task_c"],
            essential_tasks=["task_a"],
        )

        assert skill.get_effective_tasks(compact=False) == ["task_a", "task_b", "task_c"]

    def test_get_tool_schemas_compact(self) -> None:
        """Test get_tool_schemas uses essential_tasks in compact mode."""
        task_registry = create_default_registry()

        skill = Skill(
            id="test", name="Test", description="Test",
            tasks=["get_system_info", "get_current_time"],
            essential_tasks=["get_current_time"],
        )

        schemas = skill.get_tool_schemas(task_registry, compact=True)

        assert len(schemas) == 1
        assert schemas[0]["name"] == "get_current_time"

    def test_get_tool_schemas_non_compact(self) -> None:
        """Test get_tool_schemas uses full tasks when compact=False."""
        task_registry = create_default_registry()

        skill = Skill(
            id="test", name="Test", description="Test",
            tasks=["get_system_info", "get_current_time"],
            essential_tasks=["get_current_time"],
        )

        schemas = skill.get_tool_schemas(task_registry, compact=False)

        assert len(schemas) == 2

    def test_registry_get_all_tool_schemas_compact_excludes_empty(self, tmp_path: Path) -> None:
        """Test that get_all_tool_schemas(compact=True) excludes skills with empty essential_tasks."""
        task_registry = create_default_registry()

        builtin_dir = tmp_path / "builtin"

        # Skill with essential_tasks=[]  (should be excluded)
        excluded_dir = builtin_dir / "excluded"
        excluded_dir.mkdir(parents=True)
        (excluded_dir / "SKILL.md").write_text("""---
id: excluded
name: Excluded
description: Should be excluded in compact mode
tasks:
  - get_system_info
essential_tasks: []
---
""")
        # Skill with essential_tasks subset (should be included)
        included_dir = builtin_dir / "included"
        included_dir.mkdir(parents=True)
        (included_dir / "SKILL.md").write_text("""---
id: included
name: Included
description: Included in compact mode
tasks:
  - get_system_info
  - get_current_time
essential_tasks:
  - get_current_time
---
""")
        registry = SkillsRegistry(
            builtin_dir=builtin_dir,
            user_dir=tmp_path / "user",
            config_file=tmp_path / "config.json",
        )

        schemas = registry.get_all_tool_schemas(task_registry, compact=True)

        names = [s["name"] for s in schemas]
        assert "get_current_time" in names
        # get_system_info should NOT be present because the only skill that has it
        # in full tasks has essential_tasks=[], and the included skill only has
        # get_current_time in essential_tasks
        assert "get_system_info" not in names

    def test_registry_get_all_tool_schemas_non_compact_includes_all(self, tmp_path: Path) -> None:
        """Test that get_all_tool_schemas(compact=False) includes all enabled skills."""
        task_registry = create_default_registry()

        builtin_dir = tmp_path / "builtin"

        skill_dir = builtin_dir / "skill1"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("""---
id: skill1
name: Skill 1
description: Test
tasks:
  - get_system_info
essential_tasks: []
---
""")
        registry = SkillsRegistry(
            builtin_dir=builtin_dir,
            user_dir=tmp_path / "user",
            config_file=tmp_path / "config.json",
        )

        schemas = registry.get_all_tool_schemas(task_registry, compact=False)

        names = [s["name"] for s in schemas]
        assert "get_system_info" in names

    def test_format_for_prompt_compact_excludes_empty_essential(self, tmp_path: Path) -> None:
        """Test that format_for_prompt(compact=True) excludes skills with empty essential_tasks."""
        builtin_dir = tmp_path / "builtin"

        excluded_dir = builtin_dir / "excluded"
        excluded_dir.mkdir(parents=True)
        (excluded_dir / "SKILL.md").write_text("""---
id: excluded
name: Excluded Skill
description: Should not appear
tasks:
  - some_task
essential_tasks: []
---
""")
        included_dir = builtin_dir / "included"
        included_dir.mkdir(parents=True)
        (included_dir / "SKILL.md").write_text("""---
id: included
name: Included Skill
description: Should appear
tasks:
  - task_a
  - task_b
essential_tasks:
  - task_a
---
""")
        registry = SkillsRegistry(
            builtin_dir=builtin_dir,
            user_dir=tmp_path / "user",
            config_file=tmp_path / "config.json",
        )

        formatted = registry.format_for_prompt(compact=True)

        assert "Included Skill" in formatted
        assert "Excluded Skill" not in formatted

    def test_format_for_prompt_compact_shows_essential_tools(self, tmp_path: Path) -> None:
        """Test that compact prompt shows essential_tasks, not full tasks."""
        builtin_dir = tmp_path / "builtin"

        skill_dir = builtin_dir / "test"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("""---
id: test
name: Test Skill
description: Test
tasks:
  - task_a
  - task_b
  - task_c
essential_tasks:
  - task_a
---
""")
        registry = SkillsRegistry(
            builtin_dir=builtin_dir,
            user_dir=tmp_path / "user",
            config_file=tmp_path / "config.json",
        )

        formatted = registry.format_for_prompt(compact=True)

        assert "task_a" in formatted
        assert "task_b" not in formatted
        assert "task_c" not in formatted

    def test_merge_skill_propagates_essential_tasks_both(self, tmp_path: Path) -> None:
        """Test _merge_skill merges essential_tasks when both skills define it."""
        builtin_dir = tmp_path / "builtin"
        base_dir = builtin_dir / "base"
        base_dir.mkdir(parents=True)
        (base_dir / "SKILL.md").write_text("""---
id: base
name: Base Skill
description: Base
tasks:
  - task_a
  - task_b
essential_tasks:
  - task_a
---
""")
        user_dir = tmp_path / "user"
        ext_dir = user_dir / "ext"
        ext_dir.mkdir(parents=True)
        (ext_dir / "SKILL.md").write_text("""---
id: ext
extends: base
name: ext
description: Extension
tasks:
  - task_c
essential_tasks:
  - task_c
---
""")
        registry = SkillsRegistry(
            builtin_dir=builtin_dir,
            user_dir=user_dir,
            config_file=tmp_path / "config.json",
        )

        skill = registry.get("base")
        assert skill is not None
        assert skill.essential_tasks == ["task_a", "task_c"]

    def test_merge_skill_propagates_essential_tasks_base_only(self, tmp_path: Path) -> None:
        """Test _merge_skill uses base essential_tasks when extension doesn't define it."""
        builtin_dir = tmp_path / "builtin"
        base_dir = builtin_dir / "base"
        base_dir.mkdir(parents=True)
        (base_dir / "SKILL.md").write_text("""---
id: base
name: Base Skill
description: Base
tasks:
  - task_a
essential_tasks:
  - task_a
---
""")
        user_dir = tmp_path / "user"
        ext_dir = user_dir / "ext"
        ext_dir.mkdir(parents=True)
        (ext_dir / "SKILL.md").write_text("""---
id: ext
extends: base
name: ext
description: Extension
tasks:
  - task_b
---
""")
        registry = SkillsRegistry(
            builtin_dir=builtin_dir,
            user_dir=user_dir,
            config_file=tmp_path / "config.json",
        )

        skill = registry.get("base")
        assert skill is not None
        assert skill.essential_tasks == ["task_a"]

    def test_merge_skill_propagates_essential_tasks_neither(self, tmp_path: Path) -> None:
        """Test _merge_skill leaves essential_tasks as None when neither defines it."""
        builtin_dir = tmp_path / "builtin"
        base_dir = builtin_dir / "base"
        base_dir.mkdir(parents=True)
        (base_dir / "SKILL.md").write_text("""---
id: base
name: Base Skill
description: Base
tasks:
  - task_a
---
""")
        user_dir = tmp_path / "user"
        ext_dir = user_dir / "ext"
        ext_dir.mkdir(parents=True)
        (ext_dir / "SKILL.md").write_text("""---
id: ext
extends: base
name: ext
description: Extension
tasks:
  - task_b
---
""")
        registry = SkillsRegistry(
            builtin_dir=builtin_dir,
            user_dir=user_dir,
            config_file=tmp_path / "config.json",
        )

        skill = registry.get("base")
        assert skill is not None
        assert skill.essential_tasks is None

    def test_all_builtin_essential_tasks_are_subset_of_tasks(self) -> None:
        """Verify all built-in essential_tasks are a subset of tasks."""
        builtin_dir = get_builtin_skills_dir()
        registry = SkillsRegistry(
            builtin_dir=builtin_dir,
            user_dir=Path("/nonexistent"),
            config_file=Path("/tmp/test_skills_config_essential.json"),
        )

        for skill in registry.list_skills():
            if not skill.is_builtin or skill.essential_tasks is None:
                continue
            for task_name in skill.essential_tasks:
                assert task_name in skill.tasks, (
                    f"Skill '{skill.id}' has essential_task '{task_name}' "
                    f"not in tasks list: {skill.tasks}"
                )

    def test_all_builtin_essential_tasks_exist_in_registry(self) -> None:
        """Verify all built-in essential_tasks reference actually existing tasks."""
        task_registry = create_default_registry()
        builtin_dir = get_builtin_skills_dir()
        registry = SkillsRegistry(
            builtin_dir=builtin_dir,
            user_dir=Path("/nonexistent"),
            config_file=Path("/tmp/test_skills_config_essential2.json"),
        )

        for skill in registry.list_skills():
            if not skill.is_builtin or not skill.enabled or skill.essential_tasks is None:
                continue
            for task_name in skill.essential_tasks:
                task = task_registry.get(task_name)
                assert task is not None, (
                    f"Skill '{skill.id}' essential_task '{task_name}' not found in task registry"
                )


class TestRelevanceFallback:
    """Tests for lean, query-aware skill selection (get_relevant_skills)."""

    def _registry(self, tmp_path: Path) -> SkillsRegistry:
        builtin = tmp_path / "builtin"
        defs = {
            "core_utilities": ("Core Utilities", "Run shell commands and read files.", ""),
            "mail_assistant": ("Mail Assistant", "Find and act on emails over IMAP.",
                               "keywords:\n  - email\n  - inbox\n"),
            "time_tracking": ("Time Tracking", "Start, stop, and report on time tracking timers.",
                              "keywords:\n  - timer\n  - stopwatch\n"),
            "weather": ("Weather", "Get the current weather and forecast.",
                        "keywords:\n  - weather\n  - forecast\n"),
            "calendar_assistant": ("Calendar", "View and manage calendar events.",
                                   "keywords:\n  - calendar\n  - event\n"),
        }
        for sid, (name, desc, extra) in defs.items():
            d = builtin / sid
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text(
                f"---\nid: {sid}\nname: {name}\ndescription: {desc}\n{extra}---\n"
            )
        return SkillsRegistry(
            builtin_dir=builtin,
            user_dir=tmp_path / "user",
            config_file=tmp_path / "config.json",
        )

    def test_no_match_does_not_load_all(self, tmp_path: Path) -> None:
        reg = self._registry(tmp_path)
        # A query unrelated to any skill must NOT pull in every skill.
        loaded = {s.id for s in reg.get_relevant_skills("what runs every minute on my mac")}
        assert "time_tracking" not in loaded
        assert loaded != {s.id for s in reg.list_enabled_skills()}
        # Core is always present so the agent retains baseline tools.
        assert "core_utilities" in loaded

    def test_matched_skill_plus_core(self, tmp_path: Path) -> None:
        reg = self._registry(tmp_path)
        loaded = {s.id for s in reg.get_relevant_skills("check my email inbox")}
        assert "mail_assistant" in loaded
        assert "core_utilities" in loaded
        assert "time_tracking" not in loaded

    def test_zero_signal_loads_core_only(self, tmp_path: Path) -> None:
        reg = self._registry(tmp_path)
        loaded = {s.id for s in reg.get_relevant_skills("xyzzy plugh frobnicate")}
        assert loaded == {"core_utilities"}

    def test_fallback_top_k_caps_partial_matches(self, tmp_path: Path) -> None:
        reg = self._registry(tmp_path)
        reg.FALLBACK_TOP_K = 1
        # "report" appears only in time_tracking's description (partial, < threshold).
        loaded = reg.get_relevant_skills("please report")
        # core + at most 1 partial guess
        assert len(loaded) <= 2
        assert any(s.id == "core_utilities" for s in loaded)
