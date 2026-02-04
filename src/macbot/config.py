"""Configuration management for MacBot."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Macbot config directory
MACBOT_DIR = Path.home() / ".macbot"
MACBOT_ENV_FILE = MACBOT_DIR / ".env"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="MACBOT_",
        # Load from multiple locations (later files override earlier)
        # 1. ~/.macbot/.env (user config from onboard)
        # 2. .env in current directory (project-specific override)
        env_file=(str(MACBOT_ENV_FILE), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM Model setting (provider/model format)
    model: str = Field(
        default="anthropic/claude-sonnet-4-20250514",
        description="Model in provider/model format (e.g., anthropic/claude-sonnet-4-20250514, openai/gpt-4o)",
    )

    # API Keys (LiteLLM routes based on model prefix)
    anthropic_api_key: str = Field(
        default="",
        description="Anthropic API key (for anthropic/* models)",
    )
    openai_api_key: str = Field(
        default="",
        description="OpenAI API key (for openai/* models)",
    )

    # Agent settings
    max_iterations: int = Field(
        default=100,
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

5. **Be helpful, not helpless**: You have powerful tools. Use them creatively to solve the user's problem.

## Memory & Context

**Proactively remember important information** using the memory tools. When you discover something relevant to the user's life, store it for future reference:

- **Orders & shipments**: Order numbers, tracking numbers, expected delivery dates
- **Appointments & events**: Upcoming appointments, booking references, confirmation numbers
- **Subscriptions & accounts**: Service renewals, account details, billing dates
- **Travel**: Flight numbers, hotel bookings, itineraries, confirmation codes
- **Contacts & people**: Who contacted about what, important names mentioned
- **Tasks & deadlines**: Project deadlines, follow-up dates, pending actions
- **Financial**: Invoice numbers, payment due dates, transaction references
- **Personal context**: Preferences learned, frequently used accounts, important locations

Use `memory_add_fact` for specific information (e.g., "DHL tracking 00340434353522223344 for Medpex order #1h3cty").
Use `memory_add_lesson` for techniques or patterns (e.g., "Medpex sends shipping emails from auftrag@order.medpex.de").
Use `memory_set_preference` for user preferences (e.g., "Prefers brief summaries over detailed reports").

Before starting a task, check `get_agent_memory` to see recent context and avoid duplicate work.""",
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

    # Telegram settings
    telegram_bot_token: str = Field(
        default="",
        description="Telegram bot token from @BotFather",
    )
    telegram_chat_id: str = Field(
        default="",
        description="Default Telegram chat ID for sending messages",
    )
    telegram_allowed_users: list[str] = Field(
        default_factory=list,
        description="List of allowed Telegram user IDs (empty = allow all)",
    )

    # Paperless-ngx settings
    paperless_url: str = Field(
        default="",
        description="Paperless-ngx server URL (e.g., http://localhost:8000)",
    )
    paperless_api_token: str = Field(
        default="",
        description="Paperless-ngx API token",
    )

    def get_model(self) -> str:
        """Get the model string in provider/model format.

        Returns:
            Model string like 'anthropic/claude-sonnet-4-20250514'
        """
        return self.model

    def get_provider(self) -> str:
        """Get the provider name from the model string.

        Returns:
            Provider name like 'anthropic' or 'openai'
        """
        return self.model.split("/")[0] if "/" in self.model else "openai"

    def get_api_key_for_model(self, model: str | None = None) -> str | None:
        """Get the API key for a model's provider.

        Args:
            model: Model string (defaults to current model)

        Returns:
            API key string or None if not configured
        """
        model = model or self.get_model()
        provider = model.split("/")[0] if "/" in model else "openai"

        key_map = {
            "anthropic": self.anthropic_api_key,
            "openai": self.openai_api_key,
        }
        return key_map.get(provider)

    def get_cron_storage_path(self) -> Path:
        """Get the cron storage path, using default if not set."""
        if self.cron_storage_path:
            return self.cron_storage_path
        return Path.home() / ".macbot" / "cron.json"


# Global settings instance
settings = Settings()
