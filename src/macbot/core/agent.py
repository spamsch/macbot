"""Core agent loop implementation.

The agent follows a ReAct-style pattern:
1. Receive input/goal
2. Reason about what to do
3. Execute a tool if needed
4. Observe the result
5. Repeat until done or max iterations reached
"""

import json
import logging
import platform
import time
from collections.abc import Callable
from typing import Any

from rich.console import Console
from rich.panel import Panel

from macbot.config import Settings, settings
from macbot.core.task import TaskRegistry, TaskResult
from macbot.providers.base import LLMProvider, LLMResponse, Message
from macbot.providers.litellm_provider import LiteLLMProvider
from macbot.skills.registry import SkillsRegistry, get_default_registry

logger = logging.getLogger(__name__)
console = Console()


class Agent:
    """An agent that can execute tasks using an LLM.

    The agent maintains a conversation with the LLM and can execute
    registered tasks based on the LLM's tool calls.
    """

    def __init__(
        self,
        task_registry: TaskRegistry,
        provider: LLMProvider | None = None,
        config: Settings | None = None,
        skills_registry: SkillsRegistry | None = None,
        system_prompt: str | None = None,
    ) -> None:
        """Initialize the agent.

        Args:
            task_registry: Registry of available tasks
            provider: LLM provider (auto-configured from settings if not provided)
            config: Settings (uses global settings if not provided)
            skills_registry: Registry of skills (auto-loaded if not provided)
            system_prompt: Optional system prompt override (replaces default prompt,
                          system context is still appended)
        """
        self.config = config or settings
        self.task_registry = task_registry
        self.provider = provider or self._create_provider()
        self.skills_registry = skills_registry or get_default_registry()
        self._system_prompt_override = system_prompt
        self.messages: list[Message] = []
        self.iteration = 0

        # Hybrid routing state
        self._current_model: str = self.config.get_model()
        self._routing_engine = self._create_routing_engine()

        # Ensure well-known directories exist
        from macbot.core.preferences import CorePreferences
        self._preferences = CorePreferences()
        self._preferences.ensure_directories()

        # Token tracking
        self._session_input_tokens = 0
        self._session_output_tokens = 0
        self._last_context_tokens = 0  # Input tokens from last request (= context size)

    def _create_provider(self) -> LLMProvider:
        """Create an LLM provider based on configuration.

        Uses LiteLLM which supports 100+ providers via unified model string format:
        - anthropic/claude-sonnet-4-20250514
        - openai/gpt-4o
        - groq/llama3-70b-8192
        - ollama/llama2
        """
        model = self.config.get_model()
        api_key = self.config.get_api_key_for_model(model)
        api_base = self.config.get_api_base_for_model(model)

        return LiteLLMProvider(model=model, api_key=api_key, api_base=api_base)

    def _create_routing_engine(self):
        """Create a RoutingEngine if routing.json exists."""
        try:
            from macbot.core.routing import RoutingEngine, DEFAULT_CONFIG_PATH
            if DEFAULT_CONFIG_PATH.exists():
                engine = RoutingEngine(
                    skills_registry=self.skills_registry,
                )
                if engine.has_routes:
                    logger.info("Hybrid routing enabled with %d route(s)", len(engine.config.routes))
                    return engine
        except Exception as e:
            logger.debug("Routing engine not available: %s", e)
        return None

    def _maybe_switch_model(self, tool_calls) -> None:
        """Switch model based on routing rules if applicable.

        Called after tool execution each turn. If a route matches the
        tools that were just called, switches to that route's model.
        If no route matches, resets to the default model so routing
        is truly per-turn (not sticky).
        """
        if self._routing_engine is None or not self._routing_engine.has_routes:
            return

        if not tool_calls:
            return

        tool_names = [tc.name for tc in tool_calls]
        new_model = self._routing_engine.resolve(tool_names)

        # No match → fall back to the configured default model
        if new_model is None:
            new_model = self.config.get_model()

        if new_model != self._current_model:
            logger.info("Switching model: %s → %s", self._current_model, new_model)
            self._current_model = new_model
            api_key = self.config.get_api_key_for_model(new_model)
            api_base = self.config.get_api_base_for_model(new_model)
            self.provider = LiteLLMProvider(model=new_model, api_key=api_key, api_base=api_base)

    def _get_effective_profile(self) -> str:
        """Get the context profile, accounting for hybrid routing model switches.

        If context_profile is not 'auto', returns it directly.
        Otherwise infers from the current model: pico → 'compact', else → 'full'.
        """
        if self.config.context_profile != "auto":
            return self.config.context_profile
        provider = self._current_model.split("/")[0] if "/" in self._current_model else "openai"
        return "compact" if provider == "pico" else "full"

    async def run(
        self,
        goal: str | list[dict[str, Any]],
        verbose: bool = False,
        stream: bool = True,
        continue_conversation: bool = False,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> str:
        """Run the agent loop to achieve a goal.

        Args:
            goal: The objective — a string for text, or a list of content
                  blocks for multimodal input (e.g., text + image).
            verbose: Whether to print detailed output
            stream: Whether to stream LLM responses
            continue_conversation: If True, append to existing messages instead of resetting.
                                   Useful for multi-turn conversations (e.g., Telegram chat).
            on_event: Optional callback for agent events (tool_call, tool_result).

        Returns:
            The final response from the agent
        """
        if continue_conversation and self.messages:
            # Condense prior exchanges to reduce token usage and avoid
            # the LLM re-answering old questions when it sees dangling
            # tool calls / tool results without a final answer.
            self._condense_history()
            self.messages.append(Message(role="user", content=goal))
        else:
            # Start fresh conversation
            self.messages = [Message(role="user", content=goal)]
        self.iteration = 0

        # Intent-based pre-routing: check keywords before the first LLM call
        if self._routing_engine is not None and self._routing_engine.has_routes:
            goal_text = goal if isinstance(goal, str) else Message(role="user", content=goal).content_text
            intent_model = self._routing_engine.resolve_intent(goal_text or "")
            if intent_model and intent_model != self._current_model:
                logger.info("Intent pre-routing: %s → %s", self._current_model, intent_model)
                self._current_model = intent_model
                api_key = self.config.get_api_key_for_model(intent_model)
                api_base = self.config.get_api_base_for_model(intent_model)
                self.provider = LiteLLMProvider(model=intent_model, api_key=api_key, api_base=api_base)

        if verbose:
            goal_preview = goal if isinstance(goal, str) else Message(role="user", content=goal).content_text
            console.print(Panel(f"[bold]Goal:[/bold] {goal_preview}", title="Agent Started"))

        while self.iteration < self.config.max_iterations:
            self.iteration += 1

            if verbose:
                console.print(f"\n[dim]Iteration {self.iteration}/{self.config.max_iterations}[/dim]")

            # Get LLM response (with streaming if enabled)
            response = await self._get_llm_response(stream=stream, verbose=verbose)

            # If not streaming and verbose, show the response
            if not stream and verbose and response.content:
                console.print(Panel(response.content, title="Assistant"))

            # Check if we have tool calls to execute
            if response.tool_calls:
                # Show brief status when not in verbose mode
                if not verbose:
                    tool_strs = []
                    for tc in response.tool_calls:
                        if tc.arguments:
                            # Show key parameters in compact form
                            params = []
                            for k, v in tc.arguments.items():
                                v_str = str(v)
                                # Longer limit for command/script parameters
                                max_len = 100 if k in ("command", "script", "body", "notes") else 40
                                if len(v_str) > max_len:
                                    v_str = v_str[:max_len - 3] + "..."
                                params.append(f"{k}={v_str}")
                            tool_strs.append(f"{tc.name}({', '.join(params)})")
                        else:
                            tool_strs.append(tc.name)
                    # Print tool calls - one per line if multiple, single line if one
                    prefix = f"[dim][{self.iteration}/{self.config.max_iterations}] → "
                    if len(tool_strs) == 1:
                        console.print(f"{prefix}{tool_strs[0]}[/dim]")
                    else:
                        for i, ts in enumerate(tool_strs):
                            if i == 0:
                                console.print(f"{prefix}{ts}[/dim]")
                            else:
                                console.print(f"[dim]          {ts}[/dim]")
                await self._execute_tool_calls(response, verbose, on_event=on_event)
                self._maybe_switch_model(response.tool_calls)
            else:
                # No tool calls means the agent has finished
                # Store the final response so multi-turn conversations include it
                self.messages.append(Message(role="assistant", content=response.content))
                return response.content or "Task completed."

        return f"Reached maximum iterations ({self.config.max_iterations}) without completing the goal. Increase MACBOT_MAX_ITERATIONS to allow more steps."

    def _build_system_prompt(self) -> str:
        """Build a dynamic system prompt with platform and skills context.

        If a system_prompt override was provided at init, uses that instead
        of the default prompt, with system context appended.
        Dispatches to profile-specific builders based on context_profile setting.
        """
        if self._system_prompt_override is not None:
            return self._system_prompt_override + "\n" + self._build_system_context()

        profile = self._get_effective_profile()
        if profile == "compact":
            return self._build_compact_system_prompt()
        elif profile == "minimal":
            return self._build_minimal_system_prompt()
        return self._build_full_system_prompt()

    def _build_full_system_prompt(self) -> str:
        """Build the full system prompt (default for cloud models).

        Includes all sections:
        1. Base prompt (Core Principles from config)
        2. System context (platform info)
        3. Preferences
        4. Skills (full formatting with examples/body)
        5. Agent memory guidance
        6. Important rules
        7. Knowledge memory (uncapped)
        """
        prompt_parts = [self.config.agent_system_prompt]

        # Add system context
        prompt_parts.append(self._build_system_context())

        # Add core preferences (well-known directories, etc.)
        prefs_text = self._preferences.format_for_prompt()
        if prefs_text:
            prompt_parts.append("\n" + prefs_text)

        # Add skills with their tools
        skills_text = self.skills_registry.format_for_prompt(self.task_registry)
        if skills_text:
            prompt_parts.append(skills_text)

        # Add agent memory guidance
        prompt_parts.append(self._build_memory_guidance())

        # Add important rules
        prompt_parts.append(self._build_important_rules())

        # Load knowledge memory if it exists
        from macbot.memory import KnowledgeMemory
        knowledge = KnowledgeMemory()
        memory_text = knowledge.format_for_prompt()
        if memory_text:
            prompt_parts.append("\n" + memory_text)

        return "\n".join(prompt_parts)

    def _build_compact_system_prompt(self) -> str:
        """Build a compact system prompt for local models.

        Drastically reduces token count by:
        - Using a ~40-token base prompt instead of ~1,500
        - Using compact skill formatting (no examples/body)
        - Skipping memory guidance and important rules
        - Capping knowledge memory to 10 items per section
        """
        prompt_parts = [
            "You are Son of Simon, a macOS automation assistant. "
            "Call tools immediately — don't explain plans. "
            "Check memory before searching. Confirm before destructive actions."
        ]

        prompt_parts.append(self._build_system_context())

        prefs_text = self._preferences.format_for_prompt()
        if prefs_text:
            prompt_parts.append("\n" + prefs_text)

        skills_text = self.skills_registry.format_for_prompt(self.task_registry, compact=True)
        if skills_text:
            prompt_parts.append(skills_text)

        from macbot.memory import KnowledgeMemory
        knowledge = KnowledgeMemory()
        memory_text = knowledge.format_for_prompt(max_items=10)
        if memory_text:
            prompt_parts.append("\n" + memory_text)

        return "\n".join(prompt_parts)

    def _build_minimal_system_prompt(self) -> str:
        """Build a minimal system prompt for very constrained models.

        Absolute minimum context:
        - 1-sentence base prompt
        - System context only
        - No skills, preferences, memory guidance, or rules
        - Knowledge memory capped to 3 items per section
        """
        prompt_parts = [
            "You are a macOS assistant. Use tools to help the user."
        ]

        prompt_parts.append(self._build_system_context())

        from macbot.memory import KnowledgeMemory
        knowledge = KnowledgeMemory()
        memory_text = knowledge.format_for_prompt(max_items=3)
        if memory_text:
            prompt_parts.append("\n" + memory_text)

        return "\n".join(prompt_parts)

    def _build_system_context(self) -> str:
        """Build the system context section with platform info and current time."""
        from datetime import datetime
        now = datetime.now()
        return f"""
## System Context
- Current date and time: {now.strftime("%A, %B %d, %Y at %I:%M %p")}
- Platform: macOS ({platform.mac_ver()[0]})
- Architecture: {platform.machine()}
- Hostname: {platform.node()}
"""

    def _build_memory_guidance(self) -> str:
        """Build guidance for agent memory tools."""
        return """
## Agent Memory - Tracking Processed Work

You have a persistent memory to track what you've done. USE IT to avoid duplicate work:

1. **Before processing emails**: Use `get_agent_memory` to see what's already been handled
2. **After processing each email**: Use `mark_email_processed` with the Message-ID from search results
3. **After creating reminders**: Use `record_reminder_created` to track it
4. **The workflow for processing emails should be**:
   - Search for emails
   - For each email, check if already processed (via Message-ID)
   - Take action (reply, create reminder, etc.)
   - Mark as processed with action_taken (e.g., 'replied', 'reminder_created', 'reviewed', 'no_action_needed')

## Knowledge Memory Management

You can store and retrieve persistent knowledge:
- `memory_add_lesson(topic, lesson)` - Remember a technique or important discovery
- `memory_set_preference(category, preference)` - Store how the user likes things done
- `memory_add_fact(fact)` - Remember personal information about the user
- `memory_list()` - See all stored knowledge
- `memory_remove_lesson(topic)` - Remove an outdated lesson

Use these when:
- The user explicitly asks you to remember something
- You discover a workaround or technique worth recalling
- The user expresses a preference for how things should be done
- You learn factual information about the user (location, preferences, etc.)

## Reusable Web Recipes & Extraction Scripts

### Auto-save after guided navigation
When the user walks you through a website step by step (e.g., "click Settings", "scroll down", "click Billing"), you are being **taught** a navigation recipe. After completing the flow, **automatically save it** using `memory_add_lesson` with topic format `"recipe-{domain}-{action}"` (e.g., `"recipe-notion.so-check-billing"`). Include:
- The full URL to start from
- Each navigation step (what to click, scroll, type)
- The JS selectors or text labels that worked
- What data to extract at the end

### Check memory before navigating
Before attempting any website navigation, **check memory first** (`memory_list`) for a saved recipe matching the domain. If one exists, follow the stored steps directly — skip the visual snapshot trial-and-error. Only fall back to exploration if the recipe fails (page layout may have changed), and if so, update the saved recipe.

### Save extraction scripts
When you write a JavaScript snippet (via `browser_execute_js`) that successfully extracts structured data from a webpage, **save it to memory** using `memory_add_lesson` with the site domain as the topic (e.g., "golem.de extraction script"). Include the full JS code in the lesson.

### Proactive website navigation
When an email, document, or conversation implies that information is available on a website (e.g., "check your billing page", "see your account settings", "view your order status"), **proactively navigate there** instead of telling the user to do it manually. You have full browser automation — use it. Check memory for a saved recipe for that domain first.
"""

    def _build_important_rules(self) -> str:
        """Build the important rules section."""
        return """
## Important Rules

- Always try the most likely interpretation first
- When the user says "interaction" or "interactions", they likely mean email or WhatsApp messages — search both
- If a search returns no results, mention what you searched for and suggest alternatives
- Use tool parameters to filter results (today, days, mailbox, etc.) rather than asking users for them
- **NEVER use run_shell_command for tasks that have dedicated tools.** Use:
  - `create_reminder` NOT osascript for reminders
  - `send_email` NOT osascript for emails
  - `create_calendar_event` NOT osascript for events
  - `move_email` NOT osascript for moving emails
  - `download_attachments` NOT osascript for attachments
- If a dedicated tool fails, report the error. Do NOT work around it with run_shell_command.
- **Skills that document shell/CLI commands**: Many installed skills (e.g., Trello, Slack) work by running CLI commands or curl/API calls documented in their SKILL.md body. You CAN and SHOULD use `run_shell_command` to execute these commands. The skill body IS your instruction manual — follow its documented commands. Do not say "I don't have a tool for this" when the skill shows you exactly what shell commands to run.
- **Before saying "I can't do this"**: First check your Capabilities & Skills section and run `clawhub list --dir ~/.macbot/skills` to see if a skill is already installed. If it is, use it — don't search ClawHub for something you already have. If nothing is installed, search ClawHub (`clawhub search <keyword>`) for a community skill. Also consider using `web_search` to find relevant APIs or CLI tools. Only tell the user something isn't possible after you've checked installed skills, searched ClawHub, and found no options.
"""

    def _get_tool_schemas(self) -> list[dict[str, Any]]:
        """Get tool schemas appropriate for the current context profile."""
        profile = self._get_effective_profile()

        if profile == "full":
            return self.task_registry.get_tool_schemas()

        # compact/minimal: use only tools from enabled skills
        schemas = self.skills_registry.get_all_tool_schemas(self.task_registry, compact=True)

        if profile in ("compact", "minimal"):
            # Strip parameter descriptions to save tokens
            for schema in schemas:
                params = schema.get("parameters", {})
                props = params.get("properties", {})
                for prop in props.values():
                    prop.pop("description", None)

        return schemas

    def _cap_messages(self, messages: list[Message]) -> list[Message]:
        """Cap conversation history based on context profile.

        Preserves the first user message (the goal) and keeps
        tool_call/tool_result pairs together.
        """
        profile = self._get_effective_profile()

        if profile == "full":
            return messages

        max_messages = 10 if profile == "compact" else 4

        if len(messages) <= max_messages:
            return messages

        # Always keep the first user message (the goal)
        first_msg = messages[0]
        tail = messages[-(max_messages - 1):]

        # Ensure we don't start with an orphaned tool result
        # Walk forward to find a clean boundary
        start = 0
        while start < len(tail):
            if tail[start].role == "tool":
                start += 1
            elif tail[start].role == "assistant" and tail[start].tool_calls:
                # This is an assistant tool_call — check if its results follow
                # Keep it, the results should be right after
                break
            else:
                break

        capped = [first_msg] + tail[start:]
        return capped

    def _trim_messages_to_fit(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> list[Message]:
        """Drop oldest messages when approaching the context window limit.

        Always preserves the first message (the user's goal) and at least
        the most recent message group. Tool-call assistant messages and
        their corresponding tool-result messages are treated as an
        indivisible group to avoid orphaned tool results.
        """
        context_window = self.provider.get_context_window()
        if context_window is None:
            return messages

        budget = int(context_window * 0.9)
        estimated = self.provider.estimate_tokens(messages, system_prompt, tools)
        if estimated <= budget:
            return messages

        if len(messages) <= 1:
            return messages

        # Group messages into indivisible units.
        # A tool-call assistant message + its following tool results = one group.
        groups: list[list[Message]] = []
        i = 0
        while i < len(messages):
            msg = messages[i]
            if msg.role == "assistant" and msg.tool_calls:
                group = [msg]
                i += 1
                while i < len(messages) and messages[i].role == "tool":
                    group.append(messages[i])
                    i += 1
                groups.append(group)
            else:
                groups.append([msg])
                i += 1

        # Need at least the first group (goal) and the last group
        if len(groups) <= 2:
            return messages

        # In long conversations, recent context is MORE important than the
        # original goal (which may be hours old).  Always preserve at least
        # the last MIN_TAIL_GROUPS to maintain conversational coherence
        # (e.g., user confirms "yes" → we need the preceding proposal).
        min_tail = min(4, len(groups) - 1)  # last ~2 exchanges

        # Drop groups from index 1 onwards (preserve first = goal)
        # until we're under budget, but always keep the last min_tail groups.
        drop_from = 1
        max_drop = len(groups) - min_tail
        while drop_from < max_drop:
            kept = [groups[0]] + groups[drop_from:]
            flat = [m for g in kept for m in g]
            est = self.provider.estimate_tokens(flat, system_prompt, tools)
            if est <= budget:
                dropped_count = drop_from - 1
                if dropped_count > 0:
                    logger.warning(
                        "Trimmed %d message group(s) to fit context window "
                        "(%d tokens estimated, budget %d)",
                        dropped_count,
                        est,
                        budget,
                    )
                return flat
            drop_from += 1

        # Still over budget: drop the first goal too, keep only recent context.
        # In a long-running Telegram chat, the original goal from hours ago
        # is less useful than the last few exchanges.
        tail_start = max(len(groups) - min_tail, 0)
        kept = groups[tail_start:]
        flat = [m for g in kept for m in g]
        est = self.provider.estimate_tokens(flat, system_prompt, tools)
        if est <= budget:
            dropped_count = tail_start
            if dropped_count > 0:
                logger.warning(
                    "Trimmed %d message group(s) (including original goal) "
                    "to fit context window (%d tokens estimated, budget %d)",
                    dropped_count,
                    est,
                    budget,
                )
            return flat

        # Absolute worst case: even the tail is too large, keep only last group
        kept = [groups[-1]]
        flat = [m for g in kept for m in g]
        logger.warning(
            "Trimmed all but last message group to fit context window "
            "(%d tokens estimated, budget %d)",
            self.provider.estimate_tokens(flat, system_prompt, tools),
            budget,
        )
        return flat

    async def _get_llm_response(self, stream: bool = False, verbose: bool = False) -> LLMResponse:
        """Get a response from the LLM."""
        tools = self._get_tool_schemas()
        system_prompt = self._build_system_prompt()
        messages = self._cap_messages(self.messages)
        messages = self._trim_messages_to_fit(messages, system_prompt, tools)

        stream_callback = None
        if stream:
            # Create a streaming callback that prints text as it arrives
            first_chunk = [True]  # Use list to allow mutation in closure

            def stream_callback(text: str) -> None:
                if first_chunk[0]:
                    console.print("\n[bold green]A:[/bold green] ", end="")
                    first_chunk[0] = False
                console.print(text, end="", highlight=False)

        response = await self.provider.chat(
            messages=messages,
            tools=tools if tools else None,
            system_prompt=system_prompt,
            stream_callback=stream_callback,
        )

        # Track token usage
        if response.usage:
            input_tokens = response.usage.get("input_tokens", 0)
            output_tokens = response.usage.get("output_tokens", 0)
            self._session_input_tokens += input_tokens
            self._session_output_tokens += output_tokens
            self._last_context_tokens = input_tokens  # Context size = input tokens

        # Print newline after streaming completes
        if stream and response.content:
            console.print()  # End the streamed line

        return response

    async def _execute_tool_calls(
        self,
        response: LLMResponse,
        verbose: bool = False,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        """Execute tool calls from the LLM response."""
        # Add assistant message with tool calls to history
        # Must always include the tool_calls for OpenAI API compatibility
        self.messages.append(Message(
            role="assistant",
            content=response.content,
            tool_calls=response.tool_calls,
        ))

        # Execute each tool call
        for tool_call in response.tool_calls:
            if verbose:
                console.print(
                    f"\n[yellow]→ Executing tool:[/yellow] [bold]{tool_call.name}[/bold]"
                )
                if tool_call.arguments:
                    console.print(f"  [dim]Arguments:[/dim]")
                    for k, v in tool_call.arguments.items():
                        val_str = str(v)
                        if len(val_str) > 60:
                            val_str = val_str[:60] + "..."
                        console.print(f"    {k}: {val_str}")

            # Emit tool_call event
            if on_event:
                args_summary = {}
                for k, v in (tool_call.arguments or {}).items():
                    v_str = str(v)
                    if len(v_str) > 100:
                        v_str = v_str[:97] + "..."
                    args_summary[k] = v_str
                on_event({
                    "type": "tool_call",
                    "name": tool_call.name,
                    "arguments": args_summary,
                })

            t0 = time.monotonic()
            result = await self.task_registry.execute(
                tool_call.name, **tool_call.arguments
            )
            elapsed = time.monotonic() - t0

            # Emit tool_result event
            if on_event:
                on_event({
                    "type": "tool_result",
                    "name": tool_call.name,
                    "success": result.success,
                    "error": result.error if not result.success else None,
                })

            elapsed_str = f"{elapsed:.1f}s"
            if verbose:
                if result.success:
                    console.print(f"  [green]✓ Success[/green] [dim]({elapsed_str})[/dim]")
                    output_str = str(result.output) if result.output else "(no output)"
                    # Show truncated output
                    if len(output_str) > 500:
                        console.print(f"  [dim]Output (truncated):[/dim]")
                        console.print(f"    {output_str[:500]}...")
                    else:
                        console.print(f"  [dim]Output:[/dim] {output_str}")
                else:
                    console.print(f"  [red]✗ Failed ({elapsed_str})[/red]")
                    console.print(f"  [red]Error:[/red] {result.error}")
            else:
                if result.success:
                    console.print(f"[dim]  ✓ {tool_call.name} ({elapsed_str})[/dim]")
                else:
                    console.print(f"[red]  ✗ {tool_call.name} failed ({elapsed_str}):[/red] {result.error}")

            # Format and add tool result to messages
            result_content = self._format_tool_result(result)
            tool_msg = self.provider.format_tool_result(tool_call.id, result_content)
            self.messages.append(tool_msg)

    def _format_tool_result(self, result: TaskResult) -> str | list[dict[str, Any]]:
        """Format a task result for the LLM.

        Returns a string for text results, or a list of content blocks for
        multimodal results (e.g., PDF page images).

        Applies truncation based on context profile:
        - full: no truncation
        - compact: max 2,000 chars
        - minimal: max 500 chars
        """
        if result.success:
            # Check for multimodal PDF image output
            if (
                isinstance(result.output, dict)
                and result.output.get("type") == "pdf_images"
            ):
                blocks: list[dict[str, Any]] = [
                    {"type": "text", "text": result.output.get("text", "PDF document")}
                ]
                for b64_image in result.output.get("images", []):
                    blocks.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64_image}"},
                    })
                return blocks

            if isinstance(result.output, (dict, list)):
                text = json.dumps(result.output)
            else:
                text = str(result.output)
        else:
            text = f"Error: {result.error}"

        profile = self._get_effective_profile()
        max_chars = {"compact": 2000, "minimal": 500}.get(profile)

        if max_chars and len(text) > max_chars:
            text = text[:max_chars] + "... (truncated)"

        return text

    def _condense_history(self) -> None:
        """Condense completed exchanges to just user/assistant text pairs.

        In multi-turn conversations, intermediate tool_calls and tool_result
        messages from prior exchanges are no longer needed. Keeping them
        wastes tokens and can confuse the LLM into re-executing old tool
        calls or re-answering old questions.

        This walks through messages and for each completed exchange
        (user → assistant+tool_calls → tool_results → ... → assistant text),
        keeps only the user message and the final assistant text response.
        Exception: preserve the last browser-related tool call group (Safari/page
        context) so immediate follow-up questions can reference page content.
        """
        if not self.messages:
            return

        def is_browser_tool(name: str) -> bool:
            return (
                name.startswith("browser_")
                or name in {
                    "analyze_screenshot",
                    "get_current_safari_page",
                    "open_url_in_safari",
                    "extract_safari_links",
                    "list_safari_tabs",
                    # Mail context tools (keep last email results for follow-ups)
                    "get_unread_emails",
                    "search_emails",
                    "send_email",
                    "move_email",
                    "download_attachments",
                    "mark_emails_read",
                }
            )

        # Find the most recent browser-related tool group and the user message
        # it belongs to (so we can reinsert it into the condensed history).
        last_browser_group: list[Message] | None = None
        last_browser_user: Message | None = None
        current_user: Message | None = None
        i = 0
        while i < len(self.messages):
            msg = self.messages[i]
            if msg.role == "user":
                current_user = msg
                i += 1
                continue
            if msg.role == "assistant" and msg.tool_calls:
                if any(is_browser_tool(tc.name) for tc in msg.tool_calls):
                    group = [msg]
                    i += 1
                    while i < len(self.messages) and self.messages[i].role == "tool":
                        group.append(self.messages[i])
                        i += 1
                    last_browser_group = group
                    last_browser_user = current_user
                    continue
                # Skip non-browser tool groups
                i += 1
                while i < len(self.messages) and self.messages[i].role == "tool":
                    i += 1
                continue
            i += 1

        condensed: list[Message] = []
        i = 0
        while i < len(self.messages):
            msg = self.messages[i]

            if msg.role == "user":
                # Start of an exchange — keep the user message
                condensed.append(msg)
                i += 1

                # Scan forward through assistant+tool_calls and tool results
                # looking for the final assistant text response
                last_assistant_text: Message | None = None
                j = i
                while j < len(self.messages):
                    m = self.messages[j]
                    if m.role == "user":
                        # Next exchange starts — stop scanning
                        break
                    if m.role == "assistant" and not m.tool_calls and m.content:
                        # This is a final text response for this exchange
                        last_assistant_text = m
                    j += 1

                if last_assistant_text is not None:
                    # Completed exchange — keep only the final answer
                    condensed.append(last_assistant_text)
                    i = j
                else:
                    # Incomplete exchange (no final text yet) — keep everything
                    # This handles the current in-progress exchange
                    while i < len(self.messages) and self.messages[i].role != "user":
                        condensed.append(self.messages[i])
                        i += 1
            else:
                # Orphaned non-user message at the start — keep it
                condensed.append(msg)
                i += 1

        # Remove dangling tool_calls at the end (from cancelled requests).
        # An assistant message with tool_calls must be followed by tool
        # responses for every call — if not, the API rejects the request.
        while condensed:
            last = condensed[-1]
            if last.role == "tool":
                condensed.pop()
            elif last.role == "assistant" and last.tool_calls:
                condensed.pop()
            else:
                break

        # Reinsert the last browser tool group right after its user message,
        # unless it's already present (e.g., incomplete exchange).
        if last_browser_group and last_browser_user:
            if all(m is not last_browser_group[0] for m in condensed):
                try:
                    user_index = condensed.index(last_browser_user)
                except ValueError:
                    user_index = -1
                if user_index >= 0 and user_index + 1 < len(condensed):
                    condensed[user_index + 1:user_index + 1] = last_browser_group

        self.messages = condensed

    async def run_single_task(
        self, task_name: str, verbose: bool = False, **kwargs: Any
    ) -> TaskResult:
        """Run a single task directly without LLM involvement.

        Args:
            task_name: Name of the task to execute
            verbose: Whether to print output
            **kwargs: Task parameters

        Returns:
            Task result
        """
        if verbose:
            console.print(f"[yellow]Executing task:[/yellow] {task_name}")

        result = await self.task_registry.execute(task_name, **kwargs)

        if verbose:
            status = "[green]Success[/green]" if result.success else "[red]Failed[/red]"
            console.print(f"  {status}: {result.output or result.error}")

        return result

    def reset(self) -> None:
        """Reset the agent state (keeps session token counts)."""
        self.messages = []
        self.iteration = 0
        self._last_context_tokens = 0

    def reset_session(self) -> None:
        """Fully reset the agent including session token counts."""
        self.reset()
        self._session_input_tokens = 0
        self._session_output_tokens = 0

    def get_token_stats(self) -> dict[str, int]:
        """Get token usage statistics.

        Returns:
            Dictionary with token counts:
            - context_tokens: Tokens in current context (from last request)
            - session_input_tokens: Total input tokens this session
            - session_output_tokens: Total output tokens this session
            - session_total_tokens: Total tokens consumed this session
            - message_count: Number of messages in conversation
        """
        return {
            "context_tokens": self._last_context_tokens,
            "session_input_tokens": self._session_input_tokens,
            "session_output_tokens": self._session_output_tokens,
            "session_total_tokens": self._session_input_tokens + self._session_output_tokens,
            "message_count": len(self.messages),
        }
