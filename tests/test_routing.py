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

    # --- resolve_intent tests ---

    def test_resolve_intent_keyword_match(self, tmp_path: Path) -> None:
        """Keyword in user message → returns the route's model."""
        config_path = tmp_path / "routing.json"
        config_path.write_text(json.dumps({
            "routes": [
                {
                    "name": "Image Gen",
                    "skills": ["image_generation"],
                    "model": "gemini/gemini-2.5-flash",
                    "keywords": ["generate image", "create picture", "draw"],
                },
            ]
        }))

        engine = RoutingEngine(config_path=config_path)
        assert engine.resolve_intent("Please generate image of a cat") == "gemini/gemini-2.5-flash"

    def test_resolve_intent_no_keywords(self, tmp_path: Path) -> None:
        """Routes without keywords → resolve_intent returns None."""
        config_path = tmp_path / "routing.json"
        config_path.write_text(json.dumps({
            "routes": [
                {"name": "Mail", "skills": ["mail_assistant"], "model": "pico/llama3.2"},
            ]
        }))

        engine = RoutingEngine(config_path=config_path)
        assert engine.resolve_intent("search my emails") is None

    def test_resolve_intent_case_insensitive(self, tmp_path: Path) -> None:
        """Keyword matching is case-insensitive."""
        config_path = tmp_path / "routing.json"
        config_path.write_text(json.dumps({
            "routes": [
                {
                    "name": "Image Gen",
                    "skills": [],
                    "model": "gemini/gemini-2.5-flash",
                    "keywords": ["generate image"],
                },
            ]
        }))

        engine = RoutingEngine(config_path=config_path)
        assert engine.resolve_intent("GENERATE IMAGE of a dog") == "gemini/gemini-2.5-flash"
        assert engine.resolve_intent("Generate Image please") == "gemini/gemini-2.5-flash"

    def test_resolve_intent_first_match_wins(self, tmp_path: Path) -> None:
        """First route with a matching keyword wins."""
        config_path = tmp_path / "routing.json"
        config_path.write_text(json.dumps({
            "routes": [
                {
                    "name": "Route A",
                    "skills": [],
                    "model": "gemini/gemini-2.5-flash",
                    "keywords": ["draw"],
                },
                {
                    "name": "Route B",
                    "skills": [],
                    "model": "openai/gpt-5.2",
                    "keywords": ["draw"],
                },
            ]
        }))

        engine = RoutingEngine(config_path=config_path)
        assert engine.resolve_intent("draw a cat") == "gemini/gemini-2.5-flash"

    def test_resolve_intent_empty_message(self, tmp_path: Path) -> None:
        """Empty user message → None."""
        config_path = tmp_path / "routing.json"
        config_path.write_text(json.dumps({
            "routes": [
                {
                    "name": "Image Gen",
                    "skills": [],
                    "model": "gemini/gemini-2.5-flash",
                    "keywords": ["generate image"],
                },
            ]
        }))

        engine = RoutingEngine(config_path=config_path)
        assert engine.resolve_intent("") is None

    def test_keywords_backward_compatible(self, tmp_path: Path) -> None:
        """Old routing.json without keywords field still loads correctly."""
        config_path = tmp_path / "routing.json"
        config_path.write_text(json.dumps({
            "routes": [
                {"name": "Mail", "skills": ["mail_assistant"], "model": "pico/llama3.2"},
            ]
        }))

        engine = RoutingEngine(config_path=config_path)
        assert engine.has_routes
        # resolve_intent returns None since no keywords are defined
        assert engine.resolve_intent("anything") is None
        # resolve still works for tool-based routing
        skills_reg = self._make_skills_registry({"mail_assistant": ["search_emails"]})
        engine = RoutingEngine(config_path=config_path, skills_registry=skills_reg)
        assert engine.resolve(["search_emails"]) == "pico/llama3.2"

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


class TestTieredDecide:
    """Tests for the tiered, scored, complexity-aware decide() router."""

    FAST = "chatgpt/gpt-5.4-mini"
    SMART = "chatgpt/gpt-5.5"

    def _engine(self, tmp_path: Path, extra: dict | None = None) -> RoutingEngine:
        config = {
            "tiers": {"fast": self.FAST, "smart": self.SMART},
            "order": ["fast", "smart"],
            "default_tier": "fast",
            "complexity": {
                "enabled": True,
                "min_words": 40,
                "multi_skill_threshold": 3,
                "escalate_to": "smart",
                "hard_verbs": ["analyze", "compare", "summarize"],
            },
            "routes": [
                {
                    "name": "mail",
                    "tier": "smart",
                    "skills": ["mail_assistant"],
                    "min_score": 1.0,
                    "exclude_keywords": ["paperless", "document"],
                    "keywords": [
                        {"word": "inbox", "weight": 0.5},
                        "email", "unread",
                    ],
                },
            ],
        }
        if extra:
            config.update(extra)
        path = tmp_path / "routing.json"
        path.write_text(json.dumps(config))
        return RoutingEngine(config_path=path)

    def test_base_when_nothing_matches(self, tmp_path: Path) -> None:
        eng = self._engine(tmp_path)
        assert eng.decide("what's on my calendar today", [], self.FAST) == self.FAST

    def test_generic_keyword_alone_does_not_escalate(self, tmp_path: Path) -> None:
        # "inbox" weighs 0.5 < min_score 1.0 — the original false-positive bug.
        eng = self._engine(tmp_path)
        assert eng.decide("how many documents in my paperless inbox?", [], self.FAST) == self.FAST
        assert eng.decide("check my inbox", [], self.FAST) == self.FAST

    def test_exclude_keyword_blocks_route(self, tmp_path: Path) -> None:
        eng = self._engine(tmp_path)
        # "paperless" excludes the mail route even though "email" would match.
        assert eng.decide("find the paperless email document", [], self.FAST) == self.FAST

    def test_corroborated_keywords_escalate(self, tmp_path: Path) -> None:
        eng = self._engine(tmp_path)
        # inbox(0.5) + unread(1.0) = 1.5 >= 1.0
        assert eng.decide("any unread mail in my inbox?", [], self.FAST) == self.SMART

    def test_skill_match_escalates(self, tmp_path: Path) -> None:
        eng = self._engine(tmp_path)
        assert eng.decide("do the thing", ["mail_assistant"], self.FAST) == self.SMART

    def test_word_boundary_no_substring_false_positive(self, tmp_path: Path) -> None:
        eng = self._engine(tmp_path)
        # "email" must not match inside "emailing-strategy" only via substring;
        # but "wholesale" must not match "sale" etc. Here: "themailbox" != "mail".
        assert eng.decide("themailbox is a word", [], self.FAST) == self.FAST

    def test_complexity_hard_verb_escalates(self, tmp_path: Path) -> None:
        eng = self._engine(tmp_path)
        assert eng.decide("analyze my spending", [], self.FAST) == self.SMART

    def test_complexity_long_message_escalates(self, tmp_path: Path) -> None:
        eng = self._engine(tmp_path)
        long_msg = " ".join(["word"] * 45)
        assert eng.decide(long_msg, [], self.FAST) == self.SMART

    def test_complexity_multi_skill_escalates(self, tmp_path: Path) -> None:
        eng = self._engine(tmp_path)
        assert eng.decide("hi", ["a", "b", "c"], self.FAST) == self.SMART

    def test_complexity_can_be_disabled(self, tmp_path: Path) -> None:
        eng = self._engine(tmp_path, extra={
            "complexity": {"enabled": False, "hard_verbs": ["analyze"]},
        })
        assert eng.decide("analyze my spending", [], self.FAST) == self.FAST

    def test_default_tier_overrides_passed_base(self, tmp_path: Path) -> None:
        eng = self._engine(tmp_path)
        # Even if caller passes the smart model as base, default_tier=fast floors it.
        assert eng.decide("what's the weather", [], self.SMART) == self.FAST

    def test_tier_rank_orders_models(self, tmp_path: Path) -> None:
        eng = self._engine(tmp_path)
        assert eng.tier_rank(self.SMART, self.FAST) > eng.tier_rank(self.FAST, self.FAST)
        # Unknown model ranks at the floor, never escalates.
        assert eng.tier_rank("unknown/model", self.FAST) == 0

    def test_decide_with_no_tiers_legacy_config(self, tmp_path: Path) -> None:
        # Legacy config: literal models, flat keywords, no tiers/complexity off.
        path = tmp_path / "routing.json"
        path.write_text(json.dumps({
            "complexity": {"enabled": False},
            "routes": [
                {"name": "mail", "skills": ["mail_assistant"],
                 "model": "anthropic/claude-sonnet-4-5", "keywords": ["email"]},
            ],
        }))
        eng = RoutingEngine(config_path=path)
        base = "chatgpt/gpt-5.4-mini"
        assert eng.decide("send an email", [], base) == "anthropic/claude-sonnet-4-5"
        assert eng.decide("what time is it", [], base) == base


class TestMagicWord:
    """The magic word ('ultrathink') forces the strongest model."""

    FAST = "chatgpt/gpt-5.4-mini"
    SMART = "chatgpt/gpt-5.5"

    def _engine(self, tmp_path: Path, extra: dict | None = None) -> RoutingEngine:
        config: dict = {
            "tiers": {"fast": self.FAST, "smart": self.SMART},
            "order": ["fast", "smart"],
            "default_tier": "fast",
            "complexity": {"enabled": True, "hard_verbs": []},
            "routes": [
                {
                    "name": "mail", "tier": "smart", "skills": ["mail_assistant"],
                    "exclude_keywords": ["paperless"],
                    "keywords": ["email"],
                },
            ],
        }
        if extra:
            config.update(extra)
        path = tmp_path / "routing.json"
        path.write_text(json.dumps(config))
        return RoutingEngine(config_path=path)

    def test_default_magic_word_is_ultrathink(self) -> None:
        assert RoutingConfig().magic_words == ["ultrathink"]

    def test_magic_word_forces_strongest(self, tmp_path: Path) -> None:
        eng = self._engine(tmp_path)
        assert eng.decide("ultrathink what's the weather", [], self.FAST) == self.SMART

    def test_magic_word_case_insensitive(self, tmp_path: Path) -> None:
        eng = self._engine(tmp_path)
        assert eng.decide("ULTRATHINK this please", [], self.FAST) == self.SMART
        assert eng.decide("Ultrathink!", [], self.FAST) == self.SMART

    def test_magic_word_overrides_exclude_keywords(self, tmp_path: Path) -> None:
        # "paperless" would normally block the mail route; magic word wins anyway.
        eng = self._engine(tmp_path)
        assert eng.decide("ultrathink the paperless thing", [], self.FAST) == self.SMART

    def test_no_magic_word_stays_on_base(self, tmp_path: Path) -> None:
        eng = self._engine(tmp_path)
        assert eng.decide("what's the weather", [], self.FAST) == self.FAST

    def test_substring_does_not_trigger(self, tmp_path: Path) -> None:
        # Word-boundary matched: "ultrathinking" must not fire.
        eng = self._engine(tmp_path)
        assert eng.decide("ultrathinking about it", [], self.FAST) == self.FAST

    def test_custom_magic_words(self, tmp_path: Path) -> None:
        eng = self._engine(tmp_path, extra={"magic_words": ["maxbrain", "denkmal"]})
        assert eng.decide("maxbrain go", [], self.FAST) == self.SMART
        assert eng.decide("denkmal bitte", [], self.FAST) == self.SMART
        # The old default no longer applies once overridden.
        assert eng.decide("ultrathink please", [], self.FAST) == self.FAST

    def test_magic_words_can_be_disabled(self, tmp_path: Path) -> None:
        eng = self._engine(tmp_path, extra={"magic_words": []})
        assert eng.decide("ultrathink please", [], self.FAST) == self.FAST

    def test_works_with_tiers_only_no_routes(self, tmp_path: Path) -> None:
        # No routes, just tiers — engine is still active and magic word works.
        path = tmp_path / "routing.json"
        path.write_text(json.dumps({
            "tiers": {"fast": self.FAST, "smart": self.SMART},
            "order": ["fast", "smart"],
            "default_tier": "fast",
            "complexity": {"enabled": False},
            "routes": [],
        }))
        eng = RoutingEngine(config_path=path)
        assert eng.active is True
        assert eng.decide("ultrathink this", [], self.FAST) == self.SMART
        assert eng.decide("normal request", [], self.FAST) == self.FAST

    def test_no_tiers_magic_word_cannot_escalate(self, tmp_path: Path) -> None:
        # No tiers configured → nothing stronger to go to; stays on base.
        path = tmp_path / "routing.json"
        path.write_text(json.dumps({
            "complexity": {"enabled": False},
            "routes": [
                {"name": "mail", "skills": ["m"], "model": "x/y", "keywords": ["email"]},
            ],
        }))
        eng = RoutingEngine(config_path=path)
        base = self.FAST
        assert eng.decide("ultrathink please", [], base) == base
