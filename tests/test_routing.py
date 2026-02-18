"""Tests for the hybrid routing engine."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from macbot.core.routing import Route, RoutingConfig, RoutingEngine


class TestRoutingConfig:
    """Tests for RoutingConfig parsing."""

    def test_empty_config(self) -> None:
        config = RoutingConfig()
        assert config.routes == []

    def test_parse_routes(self) -> None:
        config = RoutingConfig(routes=[
            Route(name="Local", skills=["mail_assistant"], model="pico/llama3.2"),
            Route(name="Cloud", skills=["browser_automation"], model="anthropic/claude-sonnet-4-5"),
        ])
        assert len(config.routes) == 2
        assert config.routes[0].name == "Local"
        assert config.routes[0].model == "pico/llama3.2"


class TestRoutingEngine:
    """Tests for RoutingEngine."""

    def _make_skills_registry(self, skills: dict[str, list[str]] | None = None) -> MagicMock:
        """Create a mock skills registry.

        Args:
            skills: Mapping of skill_id → list of task names.
        """
        registry = MagicMock()
        mock_skills = []
        all_skills = []
        if skills:
            for skill_id, tasks in skills.items():
                skill = MagicMock()
                skill.id = skill_id
                skill.tasks = tasks
                skill.enabled = True
                mock_skills.append(skill)
                all_skills.append(skill)

        registry.list_enabled_skills.return_value = mock_skills
        registry.list_skills.return_value = all_skills
        return registry

    def test_no_routes_returns_none(self, tmp_path: Path) -> None:
        """No routes configured → resolve always returns None."""
        config_path = tmp_path / "routing.json"
        config_path.write_text("{}")
        engine = RoutingEngine(config_path=config_path)
        assert engine.resolve(["search_emails"]) is None

    def test_no_file_returns_none(self, tmp_path: Path) -> None:
        """Missing routing.json → no routes, no crash."""
        config_path = tmp_path / "nonexistent.json"
        engine = RoutingEngine(config_path=config_path)
        assert not engine.has_routes
        assert engine.resolve(["search_emails"]) is None

    def test_first_match_wins(self, tmp_path: Path) -> None:
        """First matching route wins."""
        config_path = tmp_path / "routing.json"
        config_path.write_text(json.dumps({
            "routes": [
                {"name": "Route A", "skills": ["mail_assistant"], "model": "pico/llama3.2"},
                {"name": "Route B", "skills": ["mail_assistant"], "model": "anthropic/claude-sonnet-4-5"},
            ]
        }))

        skills_reg = self._make_skills_registry({
            "mail_assistant": ["search_emails", "send_email"],
        })

        engine = RoutingEngine(config_path=config_path, skills_registry=skills_reg)
        assert engine.has_routes
        result = engine.resolve(["search_emails"])
        assert result == "pico/llama3.2"

    def test_non_matching_tools_returns_none(self, tmp_path: Path) -> None:
        """Tools not associated with any routed skill → None."""
        config_path = tmp_path / "routing.json"
        config_path.write_text(json.dumps({
            "routes": [
                {"name": "Mail Route", "skills": ["mail_assistant"], "model": "pico/llama3.2"},
            ]
        }))

        skills_reg = self._make_skills_registry({
            "mail_assistant": ["search_emails"],
            "calendar_assistant": ["get_today_events"],
        })

        engine = RoutingEngine(config_path=config_path, skills_registry=skills_reg)
        result = engine.resolve(["get_today_events"])
        assert result is None

    def test_nonexistent_skill_in_route_never_matches(self, tmp_path: Path) -> None:
        """Route referencing a non-existent skill never matches."""
        config_path = tmp_path / "routing.json"
        config_path.write_text(json.dumps({
            "routes": [
                {"name": "Ghost", "skills": ["nonexistent_skill"], "model": "pico/llama3.2"},
            ]
        }))

        skills_reg = self._make_skills_registry({
            "mail_assistant": ["search_emails"],
        })

        engine = RoutingEngine(config_path=config_path, skills_registry=skills_reg)
        result = engine.resolve(["search_emails"])
        assert result is None

    def test_empty_tool_names_returns_none(self, tmp_path: Path) -> None:
        """Empty tool names list → None."""
        config_path = tmp_path / "routing.json"
        config_path.write_text(json.dumps({
            "routes": [
                {"name": "Route A", "skills": ["mail_assistant"], "model": "pico/llama3.2"},
            ]
        }))

        engine = RoutingEngine(config_path=config_path)
        assert engine.resolve([]) is None

    def test_malformed_json_loads_empty(self, tmp_path: Path) -> None:
        """Malformed JSON → empty config, no crash."""
        config_path = tmp_path / "routing.json"
        config_path.write_text("not valid json {{{")

        engine = RoutingEngine(config_path=config_path)
        assert not engine.has_routes
        assert engine.resolve(["search_emails"]) is None

    def test_validate_missing_skill(self, tmp_path: Path) -> None:
        """Warns about skills referenced in routes but not found."""
        config_path = tmp_path / "routing.json"
        config_path.write_text(json.dumps({
            "routes": [
                {"name": "Test", "skills": ["nonexistent_skill"], "model": "pico/llama3.2"},
            ]
        }))

        skills_reg = self._make_skills_registry({
            "mail_assistant": ["search_emails"],
        })

        engine = RoutingEngine(config_path=config_path, skills_registry=skills_reg)
        warnings = engine.validate()
        assert any("nonexistent_skill" in w for w in warnings)

    def test_validate_missing_api_key(self, tmp_path: Path) -> None:
        """Warns about routes with models whose provider has no API key."""
        config_path = tmp_path / "routing.json"
        config_path.write_text(json.dumps({
            "routes": [
                {"name": "Cloud", "skills": ["mail_assistant"], "model": "anthropic/claude-sonnet-4-5"},
            ]
        }))

        skills_reg = self._make_skills_registry({
            "mail_assistant": ["search_emails"],
        })

        mock_settings = MagicMock()
        mock_settings.get_api_key_for_model.return_value = None

        engine = RoutingEngine(config_path=config_path, skills_registry=skills_reg)
        warnings = engine.validate(settings=mock_settings)
        assert any("no API key" in w for w in warnings)

    def test_validate_pico_no_api_key_warning(self, tmp_path: Path) -> None:
        """Pico routes should not warn about missing API keys."""
        config_path = tmp_path / "routing.json"
        config_path.write_text(json.dumps({
            "routes": [
                {"name": "Local", "skills": ["mail_assistant"], "model": "pico/llama3.2"},
            ]
        }))

        skills_reg = self._make_skills_registry({
            "mail_assistant": ["search_emails"],
        })

        mock_settings = MagicMock()
        mock_settings.get_api_key_for_model.return_value = None

        engine = RoutingEngine(config_path=config_path, skills_registry=skills_reg)
        warnings = engine.validate(settings=mock_settings)
        assert not any("no API key" in w for w in warnings)

    def test_reload(self, tmp_path: Path) -> None:
        """reload() picks up config changes from disk."""
        config_path = tmp_path / "routing.json"
        config_path.write_text("{}")

        skills_reg = self._make_skills_registry({
            "mail_assistant": ["search_emails"],
        })

        engine = RoutingEngine(config_path=config_path, skills_registry=skills_reg)
        assert not engine.has_routes

        # Update the file on disk
        config_path.write_text(json.dumps({
            "routes": [
                {"name": "New Route", "skills": ["mail_assistant"], "model": "pico/llama3.2"},
            ]
        }))
        engine.reload()
        assert engine.has_routes
        assert engine.resolve(["search_emails"]) == "pico/llama3.2"

    def test_multiple_skills_in_route(self, tmp_path: Path) -> None:
        """Route with multiple skills matches any of them."""
        config_path = tmp_path / "routing.json"
        config_path.write_text(json.dumps({
            "routes": [
                {
                    "name": "Local Butler",
                    "skills": ["mail_assistant", "calendar_assistant"],
                    "model": "pico/llama3.2",
                },
            ]
        }))

        skills_reg = self._make_skills_registry({
            "mail_assistant": ["search_emails"],
            "calendar_assistant": ["get_today_events"],
        })

        engine = RoutingEngine(config_path=config_path, skills_registry=skills_reg)
        assert engine.resolve(["search_emails"]) == "pico/llama3.2"
        assert engine.resolve(["get_today_events"]) == "pico/llama3.2"

    def test_validate_warns_disabled_skill(self, tmp_path: Path) -> None:
        """Validates warns about skills that exist but are disabled."""
        config_path = tmp_path / "routing.json"
        config_path.write_text(json.dumps({
            "routes": [
                {"name": "Test", "skills": ["disabled_skill"], "model": "pico/llama3.2"},
            ]
        }))

        # Create a registry with a disabled skill
        registry = MagicMock()
        disabled_skill = MagicMock()
        disabled_skill.id = "disabled_skill"
        disabled_skill.tasks = ["some_tool"]
        disabled_skill.enabled = False
        registry.list_skills.return_value = [disabled_skill]
        registry.list_enabled_skills.return_value = []

        engine = RoutingEngine(config_path=config_path, skills_registry=registry)
        warnings = engine.validate()
        assert any("disabled" in w for w in warnings)
