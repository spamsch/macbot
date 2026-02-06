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
    ) -> None:
        """Initialize the agent.

        Args:
            task_registry: Registry of available tasks
            provider: LLM provider (auto-configured from settings if not provided)
            config: Settings (uses global settings if not provided)
            skills_registry: Registry of skills (auto-loaded if not provided)
        """
        self.config = config or settings
        self.task_registry = task_registry
        self.provider = provider or self._create_provider()
        self.skills_registry = skills_registry or get_default_registry()
        self.messages: list[Message] = []
        self.iteration = 0

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

        return LiteLLMProvider(model=model, api_key=api_key)

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
        """Build a dynamic system prompt with platform and skills context.

        The prompt is structured as:
        1. Base prompt (Core Principles from config)
        2. System context (platform info)
        3. Skills section (with their tools and guidance)
        4. Agent memory guidance
        5. Important rules
        6. Knowledge memory
        """
        prompt_parts = [self.config.agent_system_prompt]

        # Add system context
        prompt_parts.append(self._build_system_context())

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
"""

    def _build_important_rules(self) -> str:
        """Build the important rules section."""
        return """
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
"""

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
