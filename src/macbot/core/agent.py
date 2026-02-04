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
from typing import Any

from rich.console import Console
from rich.panel import Panel

from macbot.config import Settings, settings
from macbot.core.task import TaskRegistry, TaskResult
from macbot.providers.anthropic import AnthropicProvider
from macbot.providers.base import LLMProvider, LLMResponse, Message
from macbot.providers.openai import OpenAIProvider

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
    ) -> None:
        """Initialize the agent.

        Args:
            task_registry: Registry of available tasks
            provider: LLM provider (auto-configured from settings if not provided)
            config: Settings (uses global settings if not provided)
        """
        self.config = config or settings
        self.task_registry = task_registry
        self.provider = provider or self._create_provider()
        self.messages: list[Message] = []
        self.iteration = 0

        # Token tracking
        self._session_input_tokens = 0
        self._session_output_tokens = 0
        self._last_context_tokens = 0  # Input tokens from last request (= context size)

    def _create_provider(self) -> LLMProvider:
        """Create an LLM provider based on configuration."""
        from macbot.config import LLMProviderType

        provider_config = self.config.get_provider_config()

        if self.config.llm_provider == LLMProviderType.ANTHROPIC:
            return AnthropicProvider(
                api_key=provider_config["api_key"],
                model=provider_config["model"],
            )
        else:
            # Note: OpenAI's native web_search requires Responses API (not yet supported)
            # For web search, the agent can use the web_search task instead
            return OpenAIProvider(
                api_key=provider_config["api_key"],
                model=provider_config["model"],
            )

    async def run(
        self,
        goal: str,
        verbose: bool = False,
        stream: bool = True,
        continue_conversation: bool = False,
    ) -> str:
        """Run the agent loop to achieve a goal.

        Args:
            goal: The objective for the agent to achieve
            verbose: Whether to print detailed output
            stream: Whether to stream LLM responses
            continue_conversation: If True, append to existing messages instead of resetting.
                                   Useful for multi-turn conversations (e.g., Telegram chat).

        Returns:
            The final response from the agent
        """
        if continue_conversation and self.messages:
            # Continue existing conversation - just add the new user message
            self.messages.append(Message(role="user", content=goal))
        else:
            # Start fresh conversation
            self.messages = [Message(role="user", content=goal)]
        self.iteration = 0

        if verbose:
            console.print(Panel(f"[bold]Goal:[/bold] {goal}", title="Agent Started"))

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
                await self._execute_tool_calls(response, verbose)
            else:
                # No tool calls means the agent has finished
                return response.content or "Task completed."

        return f"Reached maximum iterations ({self.config.max_iterations}) without completing the goal. Increase MACBOT_MAX_ITERATIONS to allow more steps."

    def _build_system_prompt(self) -> str:
        """Build a dynamic system prompt with platform and tool context."""
        # Start with the configured base prompt
        base_prompt = self.config.agent_system_prompt

        # Add platform context
        system_info = f"""

## System Context
- Platform: macOS ({platform.mac_ver()[0]})
- Architecture: {platform.machine()}
- Hostname: {platform.node()}

## Available Tools

You have access to the following tools to help accomplish tasks on this macOS system:
"""

        # Group tools by category based on naming conventions
        tools = self.task_registry.list_tasks()
        categories: dict[str, list[tuple[str, str]]] = {
            "Mail": [],
            "Calendar": [],
            "Reminders": [],
            "Notes": [],
            "Safari": [],
            "File Operations": [],
            "System": [],
        }

        for task in tools:
            name = task.name
            desc = task.description

            if "mail" in name or "email" in name:
                categories["Mail"].append((name, desc))
            elif "calendar" in name or "event" in name:
                categories["Calendar"].append((name, desc))
            elif "reminder" in name:
                categories["Reminders"].append((name, desc))
            elif "note" in name:
                categories["Notes"].append((name, desc))
            elif "safari" in name or "url" in name.lower() or "tab" in name:
                categories["Safari"].append((name, desc))
            elif "file" in name or "read" in name or "write" in name:
                categories["File Operations"].append((name, desc))
            else:
                categories["System"].append((name, desc))

        # Build tool descriptions
        tool_text = ""
        for category, task_list in categories.items():
            if task_list:
                tool_text += f"\n### {category}\n"
                for name, desc in task_list:
                    tool_text += f"- **{name}**: {desc}\n"

        # Add guidance for common scenarios
        guidance = """

## How to Handle Common Requests

- **"emails from X account"** or **"emails in X account"** → search_emails with account=X (searches ALL emails received by that account)
- **"emails from X sender/person"** → search_emails with sender=X (filters by who sent the email)
- **"today's emails"** → use today_only=true parameter
- **"recent emails"** → use days parameter (e.g., days=7 for last week)
- **"all emails" or "read and unread"** → the search includes both by default
- **"read this email" or "what does this email say"** → search_emails with message_id AND with_content=True to get full body text
- **"archive this email"** → move_email with to="archive" and message_id from search
- **"delete this email"** → move_email with to="trash" and message_id from search
- **"download attachments"** → download_attachments with output folder and message_id
- **"check my calendar"** → get_today_events or get_week_events
- **"remind me to..."** → create_reminder
- **"search notes for..."** → search_notes with the query
- **"search the web for..." or "look up..."** → web_search (fast, no browser needed)
- **"read this webpage" or "fetch this URL"** → web_fetch (extracts text from URL)

## Web Lookups

For simple web tasks, use the lightweight web_* tasks:
- **web_search** - Quick DuckDuckGo search, returns titles/URLs/snippets
- **web_fetch** - Fetch a URL and extract readable text content

Only use browser_* tasks (browser_navigate, browser_snapshot, browser_click, etc.) when you need to:
- Interact with JavaScript-heavy sites
- Fill out forms or click buttons
- Handle authentication or sessions
- See visual layout of a page

IMPORTANT: "from X account" usually means emails RECEIVED BY that account (any sender), not FROM that sender. Use the account parameter for this.

## Moving and Archiving Emails

When processing emails and the user wants them archived or deleted:
1. Use search_emails to find the email and get its Message-ID
2. Use move_email with the message_id and to="archive" or to="trash"
3. The email will be moved to the account's Archive/Trash mailbox

## Downloading Attachments

When the user wants to download email attachments:
1. Use search_emails to find the email and get its Message-ID
2. Use download_attachments with the message_id and output folder path
3. Attachments will be saved with their original filenames (duplicates auto-renamed)

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

## Important Rules

- Always try the most likely interpretation first
- If a search returns no results, mention what you searched for and suggest alternatives
- Use tool parameters to filter results (today, days, mailbox, etc.) rather than asking users for them
- **NEVER use run_shell_command for tasks that have dedicated tools.** Use:
  - `create_reminder` NOT osascript for reminders
  - `send_email` NOT osascript for emails
  - `create_calendar_event` NOT osascript for events
  - `move_email` NOT osascript for moving emails
  - `download_attachments` NOT osascript for attachments
- If a dedicated tool fails, report the error. Do NOT work around it with run_shell_command.

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
"""

        prompt_parts = [base_prompt + system_info + tool_text + guidance]

        # Load knowledge memory if it exists
        from macbot.memory import KnowledgeMemory
        knowledge = KnowledgeMemory()
        memory_text = knowledge.format_for_prompt()
        if memory_text:
            prompt_parts.append("\n" + memory_text)

        return "".join(prompt_parts)

    async def _get_llm_response(self, stream: bool = False, verbose: bool = False) -> LLMResponse:
        """Get a response from the LLM."""
        tools = self.task_registry.get_tool_schemas()
        system_prompt = self._build_system_prompt()

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
            messages=self.messages,
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
        self, response: LLMResponse, verbose: bool = False
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

            result = await self.task_registry.execute(
                tool_call.name, **tool_call.arguments
            )

            if verbose:
                if result.success:
                    console.print(f"  [green]✓ Success[/green]")
                    output_str = str(result.output) if result.output else "(no output)"
                    # Show truncated output
                    if len(output_str) > 500:
                        console.print(f"  [dim]Output (truncated):[/dim]")
                        console.print(f"    {output_str[:500]}...")
                    else:
                        console.print(f"  [dim]Output:[/dim] {output_str}")
                else:
                    console.print(f"  [red]✗ Failed[/red]")
                    console.print(f"  [red]Error:[/red] {result.error}")
            elif not result.success:
                # Always show errors, even in non-verbose mode
                console.print(f"[red]  ✗ {tool_call.name} failed:[/red] {result.error}")

            # Format and add tool result to messages
            result_str = self._format_tool_result(result)
            tool_msg = self.provider.format_tool_result(tool_call.id, result_str)
            self.messages.append(tool_msg)

    def _format_tool_result(self, result: TaskResult) -> str:
        """Format a task result as a string for the LLM."""
        if result.success:
            if isinstance(result.output, (dict, list)):
                return json.dumps(result.output)
            return str(result.output)
        else:
            return f"Error: {result.error}"

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
