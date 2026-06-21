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
        default="chatgpt/gpt-5.5",
        description="Model in provider/model format (e.g., chatgpt/gpt-5.5, anthropic/claude-sonnet-4-20250514, openai/gpt-4o)",
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
    openrouter_api_key: str = Field(
        default="",
        description="OpenRouter API key (for openrouter/* models)",
    )
    gemini_api_key: str = Field(
        default="",
        description="Google Gemini API key (for gemini/* models)",
    )

    # Pico AI Server settings (local inference)
    pico_api_base: str = Field(
        default="http://localhost:11434",
        description="Pico AI Server URL (for pico/* models)",
    )

    # ChatGPT subscription (Codex / GPT-5.x) settings. These models authenticate
    # with OAuth tokens, not an API key — MacBot reuses the Codex CLI login at
    # ~/.codex/auth.json. This dir holds the flattened copy LiteLLM reads.
    chatgpt_token_dir: str = Field(
        default="",
        description="Directory for the ChatGPT OAuth auth file (empty = ~/.macbot/chatgpt). "
                    "Used by chatgpt/* models; credentials are sourced from the Codex CLI.",
    )

    # Context profile for controlling prompt size
    context_profile: str = Field(
        default="auto",
        description="Context profile: auto, full, compact, minimal. "
                    "auto=full for cloud, compact for pico/* models",
    )

    # Agent settings
    max_iterations: int = Field(
        default=100,
        description="Maximum iterations for the agent loop",
    )
    show_reasoning: bool = Field(
        default=True,
        description="Show the model's reasoning (inline <thinking> blocks and "
                    "native reasoning tokens from reasoning models) in agent output",
    )
    max_tools: int = Field(
        default=128,
        description="Maximum number of tools sent to the LLM per request. OpenAI "
                    "rejects more than 128; excess skills are trimmed and reachable "
                    "via the request_tools escape hatch.",
    )
    skill_relevance_threshold: float = Field(
        default=0.3,
        description="Minimum relevance score (0-1) for a skill to load for a turn. "
                    "Higher = leaner tool sets, more reliance on request_tools.",
    )
    skill_fallback_top_k: int = Field(
        default=5,
        description="When no skill clears the relevance threshold, load at most "
                    "this many best-guess partial matches (plus core) instead of "
                    "all skills. The rest stay reachable via request_tools.",
    )
    agent_system_prompt: str = Field(
        default="""You are Son of Simon, a proactive macOS automation assistant. Your job is to help users accomplish tasks on their Mac.

## Thinking Process

Before acting on a request, think through your approach in a <thinking> block. This helps you plan the right strategy, avoid dead ends, and pick the best tools.

**Scale your thinking to the complexity of the task:**

- **Simple requests** (lookup, single search, straightforward action): 1-2 sentences.
  <thinking>User wants today's emails from medpex. I'll check memory for known sender patterns, then search with sender filter.</thinking>

- **Multi-step tasks** (research + action, combining multiple tools, ambiguous requests): Think through the full plan — what steps are needed, what order, what could go wrong, what depends on what. Multiple paragraphs are fine.
  <thinking>User wants to reschedule tomorrow's dentist appointment to next week. This requires several steps:
  1. First find the calendar event — search for "dentist" in tomorrow's events
  2. Check next week's availability in the calendar
  3. The dentist office likely needs to be contacted — check memory for their phone/email
  4. Then modify the calendar event to the new time
  I should start by finding the event and checking availability in parallel.</thinking>

- **Complex or risky tasks** (multi-app coordination, destructive actions, debugging failures): Think deeply. Consider edge cases, alternative approaches, and what to verify. Use multiple thinking blocks across iterations to reassess as you learn more.
  <thinking>User wants to bulk-archive all newsletters from the past month. This is a large-scale operation I should be careful with:
  - Need to identify what counts as a "newsletter" — likely recurring senders, mailing lists
  - Should search by common newsletter patterns (unsubscribe links, list-unsubscribe headers)
  - This affects many emails, so I should show the user what I found before archiving
  - I'll start by searching for emails with common newsletter sender patterns from the last 30 days, then present a summary for confirmation.</thinking>

**Use thinking blocks between iterations too.** After observing tool results, use a new <thinking> block to reassess: Did the results change the plan? Should I try a different approach? What's the next step?

After thinking, immediately proceed with tool calls. Do NOT repeat your thinking as prose to the user.

## Core Principles

1. **Think, then act**: When a user asks you to do something, think through your approach in a <thinking> block, then IMMEDIATELY call the relevant tools. Scale your thinking to the task's complexity — a quick lookup needs one sentence, a multi-step workflow needs a full plan. Use additional <thinking> blocks between iterations to reassess after observing results. Do NOT narrate your plan to the user in regular text. Just think, call tools, and present the results. For lookups and searches, always just search — never ask "do you mean X or Y?". For actions with side effects (sending emails, making bookings, purchases), confirm only the final action, not the research leading up to it.

2. **Check memory first**: Before searching, use `get_agent_memory` or `memory_list` to check for known context. The user might have orders, shipments, or contacts already stored that match what they're asking about.

3. **Handle voice transcription errors**: Voice input may have spelling mistakes (e.g., "Mad-Packs" instead of "Medpex"). If a search finds nothing:
   - Check memory for similar-sounding names
   - Try phonetic variations or partial matches
   - Only ask the user to clarify spelling as a last resort

4. **Be proactive for lookups**: For searches and information gathering, make reasonable inferences.
   If the user says "today's emails", use the today filter. If they ask about a tool or skill, search for it immediately.
   Email search without an `account` parameter already covers ALL accounts — never iterate over accounts individually.

5. **Start specific, then expand systematically**: Begin with the most targeted search first. If it returns nothing, broaden along MULTIPLE dimensions — don't just retry the same search with different keywords.
   - First try: the most specific search (e.g., sender="medpex", days=7)
   - If no results: vary the search field (e.g., subject instead of sender), widen the time range, try partial/alternative spellings
   - If still nothing: expand the search scope (e.g., all_mailboxes=True for emails, broader date ranges, removing filters one at a time)
   - Think about WHERE the data might be, not just WHAT to search for — emails can be in different mailboxes, files in different directories, etc.
   - Don't do 10 parallel searches at once - that's wasteful and slow
   - Sequential refinement is better than shotgun approach, but make sure each retry changes something meaningful

6. **Report what you found**: Even if results are empty or partial, report what you tried and what you found. Don't just say "I can't do this" - show what you attempted.

7. **Be helpful, not helpless**: You have powerful tools. Use them creatively to solve the user's problem. Think for yourself instead of bouncing questions back at the user. If there are multiple possible interpretations, pick the most likely one and go with it. NEVER ask a clarifying question when the answer is obvious from the conversation context — just act. Bad: "Which website should I log into?" (when you just discussed Notion). Good: immediately open notion.so and navigate to billing.

8. **Expand capabilities proactively**: When the user asks you to do something and you're not sure you can, don't just say you can't do it. Instead, follow this order:
   1. **Load more tools if needed**: To stay fast, only a relevant subset of your tools is loaded each turn. If you don't see a tool for the task — or for the next step — call `request_tools` with the matching group id(s) (its description lists every available group) and then continue. Hitting a missing-tool roadblock means request more tools, not give up.
   2. **Check your skills first**: Review the Capabilities & Skills section in this prompt — you may already have an installed skill for it (e.g., Slack, Trello, WhatsApp). Also run `clawhub list --dir ~/.macbot/skills` to check for installed skills that may not be enabled yet. If a skill is already installed, use it immediately — don't search ClawHub for something you already have.
   3. **Search ClawHub** for a community skill if nothing is installed: `clawhub search <keyword>`
   4. **Search the web** using `web_search` for APIs, CLIs, or tools that could help
   - If a ClawHub skill exists, offer to install it and use it immediately
   - If a CLI tool or API exists, suggest how to set it up
   - Only say "this isn't possible" after you've checked your installed skills, searched ClawHub, and found nothing

9. **Focus on the current message, but use conversation context**: In multi-turn conversations, answer ONLY the user's latest message — don't re-answer or rehash previous questions. BUT: always use the full conversation history to understand what the user means.
   - **Pronouns and references** like "there", "that", "it", "da", "das", "davon" refer to the topic just discussed. Example: if you just discussed a Notion billing email and the user says "can you log in there and check?", "there" = Notion.
   - **Implicit scoping from active context**: When you've been interacting with a specific app or website, follow-up requests are scoped to that context. Example: if you just browsed LinkedIn and the user says "what are my notifications?", that means LinkedIn notifications — navigate to linkedin.com/notifications. Don't check email, macOS notification center, or ask "which service?".
   - Never ask "where?" or "which service?" when the answer is obvious from the conversation or current browser/app context.

10. **Only confirm destructive or costly actions**: Searching, reading, listing, and fetching information should NEVER require user confirmation. Only ask before: sending messages, creating/modifying events, making purchases, deleting things, or other actions with real-world side effects that can't be undone.

11. **"Yes" means do it**: When you propose an action and the user confirms ("ja", "ja bitte", "yes", "mach das", "ok", "do it", "go ahead", "sure"), IMMEDIATELY execute the action you proposed. NEVER ask "what do you mean?" or "which action?" — you just proposed it, so you know exactly what to do. This is critical: the user is confirming YOUR suggestion, not making a new request.

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
    subagent_model: str = Field(
        default="",
        description="Override model for subagents (empty = auto by tier)",
    )
    subagent_max_iterations: int = Field(
        default=30,
        description="Maximum iterations for subagent loops",
    )
    subagent_timeout: int = Field(
        default=120,
        description="Timeout in seconds for subagent execution",
    )
    queue_warn_after_ms: int = Field(
        default=5000,
        description="Warning threshold for queue wait time in milliseconds",
    )

    # Heartbeat settings
    heartbeat_interval: int = Field(
        default=1800,
        description="Heartbeat interval in seconds (default: 1800 = 30 minutes)",
    )
    heartbeat_active_start: int = Field(
        default=7,
        description="Heartbeat active hours start (24h format, default: 7 = 7 AM)",
    )
    heartbeat_active_end: int = Field(
        default=23,
        description="Heartbeat active hours end (24h format, default: 23 = 11 PM)",
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

    # Things3 settings
    things_auth_token: str = Field(
        default="",
        description="Things3 URL scheme auth token (from Things → Settings → General → Enable Things URLs)",
    )

    # Mindwtr settings
    mindwtr_data_path: str = Field(
        default="",
        description="Path to Mindwtr sync data.json file (leave empty to disable Mindwtr integration)",
    )

    # Mail.app (AppleScript) tasks. Off by default — they need Mail.app running and
    # are superseded by the headless IMAP mail tasks (mail_imap_*). Set
    # MACBOT_ENABLE_MAILAPP_TASKS=true to re-enable get_unread_emails, search_emails,
    # send_email, move_email, download_attachments, mark_emails_read.
    enable_mailapp_tasks: bool = Field(
        default=False,
        description="Enable the legacy Mail.app/AppleScript email tasks (default: disabled).",
    )

    # Headless IMAP mail: multi-tenant Azure app id used for Microsoft device-code login.
    ms_oauth_client_id: str = Field(
        default="",
        description="Azure AD app (multi-tenant public client) id for headless IMAP OAuth.",
    )

    def get_model(self) -> str:
        """Get the model string in provider/model format.

        Returns:
            Model string like 'anthropic/claude-sonnet-4-20250514'
        """
        return self.model

    def get_context_profile(self) -> str:
        """Resolve the effective context profile.

        Returns:
            'full', 'compact', or 'minimal'
        """
        if self.context_profile != "auto":
            return self.context_profile
        return "compact" if self.get_provider() == "pico" else "full"

    def get_provider(self) -> str:
        """Get the provider name from the model string.

        Returns:
            Provider name like 'anthropic' or 'openai'
        """
        return self.model.split("/")[0] if "/" in self.model else "openai"

    def _resolve_key(self, field_name: str, env_value: str) -> str:
        """Resolve an API key, checking Keychain first then .env.

        Args:
            field_name: Keychain account name (e.g. 'anthropic_api_key')
            env_value: The value from the .env / Settings field

        Returns:
            The resolved key (Keychain wins) or the env_value as fallback.
        """
        try:
            from macbot.core.keychain import get_keychain
            kc_value = get_keychain(field_name)
            if kc_value:
                return kc_value
        except Exception:
            pass
        return env_value

    def get_api_key_for_model(self, model: str | None = None) -> str | None:
        """Get the API key for a model's provider.

        Checks macOS Keychain first, falls back to .env value.

        Args:
            model: Model string (defaults to current model)

        Returns:
            API key string or None if not configured
        """
        model = model or self.get_model()
        provider = model.split("/")[0] if "/" in model else "openai"

        # Keyless providers: pico (local) and chatgpt (OAuth via Codex CLI).
        if provider in ("pico", "chatgpt"):
            return None

        key_map = {
            "anthropic": self._resolve_key("anthropic_api_key", self.anthropic_api_key),
            "openai": self._resolve_key("openai_api_key", self.openai_api_key),
            "openrouter": self._resolve_key("openrouter_api_key", self.openrouter_api_key),
            "gemini": self._resolve_key("gemini_api_key", self.gemini_api_key),
        }
        return key_map.get(provider)

    def get_api_base_for_model(self, model: str | None = None) -> str | None:
        """Get the API base URL for a model's provider.

        Args:
            model: Model string (defaults to current model)

        Returns:
            API base URL or None if not needed
        """
        model = model or self.get_model()
        provider = model.split("/")[0] if "/" in model else "openai"
        if provider == "pico":
            return self.pico_api_base
        return None

    def get_cron_storage_path(self) -> Path:
        """Get the cron storage path, using default if not set."""
        if self.cron_storage_path:
            return self.cron_storage_path
        return Path.home() / ".macbot" / "cron.json"


# Global settings instance
settings = Settings()
