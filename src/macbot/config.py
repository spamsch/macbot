"""Configuration management for MacBot."""

from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProviderType(str, Enum):
    """Supported LLM providers."""

    ANTHROPIC = "anthropic"
    OPENAI = "openai"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="MACBOT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM Provider settings
    llm_provider: LLMProviderType = Field(
        default=LLMProviderType.ANTHROPIC,
        description="The LLM provider to use",
    )

    # Anthropic settings
    anthropic_api_key: str = Field(
        default="",
        description="Anthropic API key",
    )
    anthropic_model: str = Field(
        default="claude-sonnet-4-20250514",
        description="Anthropic model to use",
    )

    # OpenAI settings
    openai_api_key: str = Field(
        default="",
        description="OpenAI API key",
    )
    openai_model: str = Field(
        default="gpt-4o",
        description="OpenAI model to use",
    )

    # Agent settings
    max_iterations: int = Field(
        default=10,
        description="Maximum iterations for the agent loop",
    )
    agent_system_prompt: str = Field(
        default="""You are MacBot, a proactive macOS automation assistant. Your job is to help users accomplish tasks on their Mac.

## Core Principles

1. **Be proactive, not passive**: When a user asks for something, TRY IT first rather than asking clarifying questions. Make reasonable inferences from context.

2. **Infer parameters from context**: If the user mentions "waas.rent account", search for sender containing "waas.rent". If they say "today's emails", use the today filter. Don't ask for parameters you can reasonably guess.

3. **Try multiple approaches**: If one tool call fails or returns no results, try a different approach. For example:
   - If searching by sender returns nothing, try searching by subject
   - If today returns nothing, try the last few days
   - If one mailbox is empty, check others

4. **Report what you found**: Even if results are empty or partial, report what you tried and what you found. Don't just say "I can't do this" - show what you attempted.

5. **Be helpful, not helpless**: You have powerful tools. Use them creatively to solve the user's problem.""",
        description="System prompt for the agent",
    )

    # Scheduler settings
    default_interval_seconds: int = Field(
        default=60,
        description="Default interval between scheduled task runs in seconds",
    )

    # Command Queue settings
    main_lane_concurrency: int = Field(
        default=1,
        description="Maximum concurrent tasks in main lane",
    )
    cron_lane_concurrency: int = Field(
        default=1,
        description="Maximum concurrent tasks in cron lane",
    )
    subagent_lane_concurrency: int = Field(
        default=2,
        description="Maximum concurrent tasks in subagent lane",
    )
    queue_warn_after_ms: int = Field(
        default=5000,
        description="Warning threshold for queue wait time in milliseconds",
    )

    # Cron settings
    cron_storage_path: Path | None = Field(
        default=None,
        description="Path for cron job storage (default: ~/.macbot/cron.json)",
    )
    cron_enabled: bool = Field(
        default=True,
        description="Whether the cron service is enabled",
    )

    # Followup Queue settings
    followup_queue_mode: str = Field(
        default="collect",
        description="Followup queue mode: collect, followup, or interrupt",
    )
    followup_queue_cap: int = Field(
        default=100,
        description="Maximum followup queue size",
    )
    followup_debounce_ms: int = Field(
        default=500,
        description="Debounce delay for followup processing in milliseconds",
    )
    followup_drop_policy: str = Field(
        default="old",
        description="Drop policy when queue is full: old, new, or summarize",
    )

    def get_provider_config(self) -> dict[str, Any]:
        """Get configuration for the selected LLM provider."""
        if self.llm_provider == LLMProviderType.ANTHROPIC:
            return {
                "api_key": self.anthropic_api_key,
                "model": self.anthropic_model,
            }
        else:
            return {
                "api_key": self.openai_api_key,
                "model": self.openai_model,
            }

    def get_cron_storage_path(self) -> Path:
        """Get the cron storage path, using default if not set."""
        if self.cron_storage_path:
            return self.cron_storage_path
        return Path.home() / ".macbot" / "cron.json"


# Global settings instance
settings = Settings()
