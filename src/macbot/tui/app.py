"""Full-screen Textual TUI for Son of Simon chat.

Inspired by opencode's terminal UI: scrollable message area,
multi-line input editor, live status bar with model/tokens/cost.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.command import Hit, Hits, Provider
from textual.containers import Vertical, VerticalScroll
from textual.message import Message as TMessage
from textual.reactive import reactive
from textual.widgets import Footer, Markdown, Static, TextArea

from macbot import __version__
from macbot.config import settings
from macbot.core.agent import Agent
from macbot.core.channel import ChannelKind, ChannelRegistry
from macbot.providers.base import Message
from macbot.tasks import create_default_registry
from macbot.tui import history


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------

class ThinkingIndicator(Static):
    """Animated braille spinner with cycling label."""

    _frame: reactive[int] = reactive(0)
    _spinner = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    _labels = [
        "Thinking",
        "Reasoning",
        "Working",
        "Processing",
    ]

    def on_mount(self) -> None:
        self.set_interval(0.08, self._tick)

    def _tick(self) -> None:
        self._frame += 1

    def render(self) -> str:
        char = self._spinner[self._frame % len(self._spinner)]
        label = self._labels[(self._frame // 40) % len(self._labels)]
        bar_len = (self._frame // 2) % 4
        dots = "·" * bar_len + " " * (3 - bar_len)
        return f" {char} {label}{dots}"


class StatusBar(Static):
    """Top status bar: model, tasks, token stats, cost."""

    model_name: reactive[str] = reactive("")
    token_info: reactive[str] = reactive("")
    task_count: reactive[int] = reactive(0)

    def render(self) -> str:
        parts = [f"Son of Simon v{__version__}"]
        if self.model_name:
            parts.append(f"Model: {self.model_name}")
        if self.task_count:
            parts.append(f"Tasks: {self.task_count}")
        if self.token_info:
            parts.append(self.token_info)
        return " | ".join(parts)


class PromptInput(TextArea):
    """Multi-line input area with Enter-to-send, Alt+Enter for newline.

    TextArea._on_key intercepts Enter before bindings fire, so we
    override _on_key to catch Enter (submit) and shift+enter/alt+enter
    (insert newline) ourselves.
    """

    DEFAULT_CSS = """
    PromptInput {
        height: auto;
        max-height: 8;
        min-height: 3;
        margin: 0 0 1 0;
        border: tall $accent;
    }
    PromptInput:focus {
        border: tall $accent;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel_run", "Cancel", show=False),
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            language=None,
            soft_wrap=True,
            show_line_numbers=False,
            **kwargs,
        )

    class Submitted(TMessage):
        """User pressed Enter to submit."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class CancelRun(TMessage):
        """User pressed Escape to cancel a running agent."""

    async def _on_key(self, event: Any) -> None:
        if event.key == "enter":
            # Enter = submit
            event.stop()
            event.prevent_default()
            text = self.text.strip()
            if text:
                self.post_message(self.Submitted(text))
                self.clear()
            return

        if event.key in ("shift+enter", "alt+enter"):
            # Shift+Enter / Alt+Enter = insert newline
            event.stop()
            event.prevent_default()
            start, end = self.selection
            self._replace_via_keyboard("\n", start, end)
            return

        # Everything else: default TextArea behaviour
        await super()._on_key(event)

    def action_cancel_run(self) -> None:
        self.post_message(self.CancelRun())


# ---------------------------------------------------------------------------
# Command Palette Provider
# ---------------------------------------------------------------------------

class ChatCommands(Provider):
    """Provides commands for the chat command palette."""

    async def discover(self) -> Hits:
        app = self.app
        assert isinstance(app, ChatApp)

        yield Hit(1.0, "Clear conversation", app.action_clear_chat, help="Reset chat and start a new session")
        yield Hit(0.9, "Show stats", app.action_show_stats, help="Token usage statistics")
        yield Hit(0.8, "Show tasks", app._show_tasks, help="List available agent tasks")
        yield Hit(0.7, "Sessions", app._show_sessions, help="List saved sessions")
        yield Hit(0.6, "Channels", app._show_channels, help="List all channels")
        yield Hit(0.5, "Quit", app.action_quit, help="Exit the application")

        # List channels as switchable items
        if app._channels is not None:
            for ch in app._channels.list_channels():
                active = " (active)" if ch.id == app._channels.active_id else ""
                msg_count = len(ch.agent.messages)

                def _make_switcher(_cid: str = ch.id) -> None:
                    app._switch_channel(_cid)

                yield Hit(
                    0.55,
                    f"Switch to channel: {ch.name}{active}",
                    _make_switcher,
                    help=f"{ch.id} · {ch.kind.value} · {msg_count} msgs",
                )

        # List saved sessions as loadable items
        sessions = history.list_sessions()
        for s in sessions[:5]:
            sid = s["id"]
            title = s["title"] or "(untitled)"
            if len(title) > 50:
                title = title[:47] + "..."
            count = s["message_count"]
            created = s.get("created", "")[:16].replace("T", " ")

            def _make_loader(_sid: str = sid) -> None:
                app._load_session(_sid)

            yield Hit(
                0.3,
                f"Load session: {title}",
                _make_loader,
                help=f"{sid} · {count} msgs · {created}",
            )

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        async for hit in self.discover():
            display = hit.match_display
            text = display if isinstance(display, str) else str(display)
            score = matcher.match(text)
            if score > 0:
                yield Hit(score, matcher.highlight(text), hit.command, help=hit.help)


# ---------------------------------------------------------------------------
# Main Application
# ---------------------------------------------------------------------------

class ChatApp(App[None]):
    """Full-screen chat TUI for Son of Simon."""

    TITLE = "Son of Simon"
    COMMANDS = {ChatCommands}
    COMMAND_PALETTE_BINDING = "ctrl+p"

    CSS = """
    Screen {
        layout: vertical;
    }
    #status-bar {
        dock: top;
        height: 1;
        background: $primary-darken-3;
        color: $text;
        padding: 0 1;
    }
    #messages {
        height: 1fr;
        scrollbar-size: 1 1;
        border: round $primary-darken-2;
    }
    #input-container {
        dock: bottom;
        height: auto;
        max-height: 10;
    }
    .msg-user {
        color: $accent;
        padding: 0 1;
        margin: 1 0 0 0;
    }
    .msg-status {
        color: $text-muted;
        padding: 0 1;
        margin: 0;
    }
    .msg-error {
        color: $error;
        padding: 0 1;
        margin: 0;
    }
    .msg-tool {
        color: $text-muted;
        padding: 0 1 0 3;
        margin: 0;
    }
    .msg-sep {
        color: $text-muted;
        padding: 0 1;
        margin: 0;
    }
    .msg-md {
        margin: 1 0 0 0;
        padding: 0 1;
    }
    .thinking {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("ctrl+c,super+c", "copy_or_quit", "Copy/Quit", show=False, priority=True),
        Binding("ctrl+q", "quit", "Quit", show=True),
        Binding("ctrl+l", "clear_chat", "Clear", show=True),
        Binding("ctrl+t", "show_stats", "Stats", show=True),
    ]

    def __init__(
        self,
        agent: Agent | None = None,
        service_mode: bool = False,
        service: Any | None = None,
        channels: ChannelRegistry | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        self._agent = agent
        self._channels = channels
        self._service_mode = service_mode
        self._service = service
        self._cancel_event: asyncio.Event | None = None
        self._service_task: asyncio.Task | None = None  # type: ignore[type-arg]
        self._session_id: str | None = None

    def compose(self) -> ComposeResult:
        yield StatusBar(id="status-bar")
        yield VerticalScroll(id="messages")
        with Vertical(id="input-container"):
            yield PromptInput(id="prompt")
        yield Footer()

    async def on_mount(self) -> None:
        if self._channels is not None:
            # Use the active channel's agent
            self._agent = self._channels.active.agent
        elif self._agent is None:
            registry = create_default_registry()
            self._agent = Agent(registry)

        bar = self.query_one("#status-bar", StatusBar)
        if self._channels is not None:
            bar.model_name = f"{settings.model} | {self._channels.active.name}"
        else:
            bar.model_name = settings.model
        bar.task_count = len(self._agent.task_registry)

        # Start a fresh session
        self._session_id = history.create_session()

        # Start service background tasks (cron, telegram, heartbeat) in service mode
        if self._service_mode and self._service is not None:
            self._service_task = asyncio.create_task(
                self._service.start(interactive=False, stdin_reader=False)
            )

        self.query_one("#prompt", PromptInput).focus()

    # ----- Input handling -----

    @on(PromptInput.Submitted)
    def _on_submit(self, event: PromptInput.Submitted) -> None:
        text = event.text
        cmd = text.lower()

        if cmd in ("quit", "exit", "q"):
            self._print_final_stats()
            self.action_quit()
            return
        if cmd == "clear":
            self.action_clear_chat()
            return
        if cmd == "stats":
            self.action_show_stats()
            return
        if cmd == "help":
            self._add_md(
                "**Commands:** quit, clear, stats, help, tasks, sessions, load &lt;id&gt;, "
                "channels, ch &lt;id&gt;, channel new &lt;name&gt;, channel close &lt;id&gt;\n\n"
                "**Keys:** Enter=send, Shift+Enter=newline, Escape=cancel, "
                "Ctrl+P=command palette, Ctrl+L=clear, Ctrl+T=stats"
            )
            return
        if cmd == "tasks":
            self._show_tasks()
            return
        if cmd == "sessions":
            self._show_sessions()
            return
        if cmd.startswith("load "):
            self._load_session(text[5:].strip())
            return
        if cmd in ("channels", "ch"):
            self._show_channels()
            return
        if cmd.startswith("ch ") or cmd.startswith("channel switch "):
            target = text.split(maxsplit=2)[-1].strip() if " " in text else ""
            if target:
                self._switch_channel(target)
            else:
                self._show_channels()
            return
        if cmd.startswith("channel new "):
            name = text[len("channel new "):].strip()
            if name:
                self._create_channel(name)
            return
        if cmd.startswith("channel close "):
            cid = text[len("channel close "):].strip()
            if cid:
                self._close_channel(cid)
            return

        self._add_text(f"You: {text}", "msg-user")
        if self._session_id:
            history.append(self._session_id, "user", text)
        self._run_agent(text)

    @on(PromptInput.CancelRun)
    def _on_cancel(self) -> None:
        if self._cancel_event:
            self._cancel_event.set()

    # ----- Agent worker -----

    @work(exclusive=True, thread=False)
    async def _run_agent(self, text: str) -> None:
        if not self._agent:
            return

        prompt = self.query_one("#prompt", PromptInput)
        prompt.disabled = True
        self._cancel_event = asyncio.Event()

        area = self.query_one("#messages", VerticalScroll)

        # Show thinking indicator
        thinking = ThinkingIndicator(classes="thinking")
        await area.mount(thinking)
        area.scroll_end(animate=False)

        def _status_cb(msg: str) -> None:
            self._add_text(msg, "msg-tool")

        try:
            coro = self._agent.run(
                text,
                verbose=False,
                stream=False,
                continue_conversation=True,
                on_event=self._on_agent_event,
                on_status=_status_cb,
            )

            # Race: agent vs cancel
            agent_task = asyncio.ensure_future(coro)
            cancel_task = asyncio.ensure_future(self._cancel_event.wait())

            done, _ = await asyncio.wait(
                [agent_task, cancel_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Remove thinking indicator
            try:
                thinking.remove()
            except Exception:
                pass

            if agent_task in done:
                cancel_task.cancel()
                result = agent_task.result()

                # Mount answer markdown after all tool status messages
                md_widget = Markdown(result, classes="msg-md")
                await area.mount(md_widget)
                area.scroll_end(animate=False)

                if self._session_id:
                    history.append(self._session_id, "assistant", result)
                self._update_token_bar()
                self._add_text("─" * 60, "msg-sep")
            else:
                # Cancelled
                agent_task.cancel()
                try:
                    await agent_task
                except (asyncio.CancelledError, Exception):
                    pass
                self._add_text("[Cancelled]", "msg-status")

        except Exception as e:
            try:
                thinking.remove()
            except Exception:
                pass
            self._add_text(f"Error: {e}", "msg-error")

        finally:
            self._cancel_event = None
            prompt.disabled = False
            prompt.focus()

    def _on_agent_event(self, event: dict[str, Any]) -> None:
        """Handle on_event callbacks from the agent (tool_call / tool_result)."""
        # These already get handled via on_status for the non-verbose path.
        # on_event is kept for the JSON-lines protocol compatibility.
        pass

    # ----- UI helpers -----

    def _add_text(self, text: str, css_class: str = "") -> None:
        area = self.query_one("#messages", VerticalScroll)
        area.mount(Static(text, classes=css_class))
        area.scroll_end(animate=False)

    def _add_md(self, text: str) -> None:
        area = self.query_one("#messages", VerticalScroll)
        area.mount(Markdown(text, classes="msg-md"))
        area.scroll_end(animate=False)

    def _update_token_bar(self) -> None:
        if not self._agent:
            return
        stats = self._agent.get_token_stats()
        ctx = _fmt_tokens(stats["context_tokens"])
        total = _fmt_tokens(stats["session_total_tokens"])
        cost = _fmt_cost(stats.get("session_cost"))
        parts = [f"ctx:{ctx}", f"total:{total}"]
        if cost:
            parts.append(cost)
        self.query_one("#status-bar", StatusBar).token_info = " ".join(parts)

    def _show_tasks(self) -> None:
        if not self._agent:
            return
        lines = ["**Available Tasks:**\n"]
        for task in sorted(self._agent.task_registry.list_tasks(), key=lambda t: t.name):
            desc = task.description[:57] + "..." if len(task.description) > 60 else task.description
            lines.append(f"- `{task.name}` — {desc}")
        self._add_md("\n".join(lines))

    def _print_final_stats(self) -> None:
        if not self._agent:
            return
        stats = self._agent.get_token_stats()
        if stats["session_total_tokens"] > 0:
            cost = _fmt_cost(stats.get("session_cost"))
            cost_part = f", cost: {cost}" if cost else ""
            self._add_text(
                f"Session: {stats['session_total_tokens']:,} tokens "
                f"(in: {stats['session_input_tokens']:,}, "
                f"out: {stats['session_output_tokens']:,}{cost_part})",
                "msg-status",
            )

    def _show_sessions(self) -> None:
        sessions = history.list_sessions()
        if not sessions:
            self._add_text("No saved sessions.", "msg-status")
            return
        lines = ["**Sessions** (type `load <id>` to restore)\n"]
        for s in sessions[:20]:
            sid = s["id"]
            title = s["title"] or "(untitled)"
            if len(title) > 60:
                title = title[:57] + "..."
            count = s["message_count"]
            created = s.get("created", "")[:16].replace("T", " ")
            current = " ← current" if sid == self._session_id else ""
            lines.append(f"- `{sid}` {title} ({count} msgs, {created}){current}")
        self._add_md("\n".join(lines))

    def _load_session(self, session_id: str) -> None:
        entries = history.load_session(session_id)
        if not entries:
            self._add_text(f"Session '{session_id}' not found or empty.", "msg-error")
            return

        # Reset agent and UI
        if self._agent:
            self._agent.reset()
        self.query_one("#messages", VerticalScroll).remove_children()

        # Switch to the loaded session
        self._session_id = session_id

        # Replay messages into UI and agent
        for entry in entries:
            role = entry.get("role", "")
            text = entry.get("text", "")
            if role == "user":
                self._add_text(f"You: {text}", "msg-user")
                if self._agent:
                    self._agent.messages.append(Message(role="user", content=text))
            elif role == "assistant":
                self._add_md(text)
                self._add_text("─" * 60, "msg-sep")
                if self._agent:
                    self._agent.messages.append(Message(role="assistant", content=text))

        area = self.query_one("#messages", VerticalScroll)
        area.scroll_end(animate=False)
        self._add_text(f"Session '{session_id}' loaded.", "msg-status")

    # ----- Channel management -----

    def _show_channels(self) -> None:
        if self._channels is None:
            self._add_text("Channels not available (not in service mode).", "msg-status")
            return
        lines = ["**Channels** (use command palette to switch)\n"]
        for ch in self._channels.list_channels():
            active = " **[active]**" if ch.id == self._channels.active_id else ""
            msg_count = len(ch.agent.messages)
            lines.append(f"- `{ch.id}` {ch.name} ({ch.kind.value}, {msg_count} msgs){active}")
        self._add_md("\n".join(lines))

    def _switch_channel(self, channel_id: str) -> None:
        if self._channels is None:
            self._add_text("Channels not available.", "msg-error")
            return
        try:
            ch = self._channels.switch(channel_id)
        except KeyError:
            self._add_text(f"Channel '{channel_id}' not found.", "msg-error")
            return

        # Switch agent and clear UI
        self._agent = ch.agent
        self.query_one("#messages", VerticalScroll).remove_children()

        # Create a new session for this channel view
        self._session_id = history.create_session()

        # Replay existing agent messages into UI
        for msg in ch.agent.messages:
            if msg.role == "user":
                self._add_text(f"You: {msg.content_text}", "msg-user")
            elif msg.role == "assistant" and not msg.tool_calls:
                self._add_md(msg.content_text)
                self._add_text("─" * 60, "msg-sep")

        self._update_token_bar()
        bar = self.query_one("#status-bar", StatusBar)
        bar.model_name = f"{settings.model} | {ch.name}"
        self._add_text(f"Switched to channel: {ch.name} ({ch.id})", "msg-status")

    def _create_channel(self, name: str) -> None:
        if self._channels is None:
            self._add_text("Channels not available.", "msg-error")
            return
        try:
            ch = self._channels.create_custom_channel(name)
            self._add_text(f"Created channel: {ch.name} ({ch.id})", "msg-status")
        except ValueError as e:
            self._add_text(str(e), "msg-error")

    def _close_channel(self, channel_id: str) -> None:
        if self._channels is None:
            self._add_text("Channels not available.", "msg-error")
            return
        if self._channels.close(channel_id):
            self._add_text(f"Closed channel: {channel_id}", "msg-status")
            # If we closed the active channel, switch to main
            if self._channels.active_id == "main" and channel_id != "main":
                self._switch_channel("main")
        else:
            self._add_text(f"Cannot close '{channel_id}' (not found or not a custom channel).", "msg-error")

    # ----- Actions -----

    def action_copy_or_quit(self) -> None:
        """Ctrl+C: copy selected text if any, otherwise quit."""
        text = self.screen.get_selected_text()
        if text:
            self.copy_to_clipboard(text)
            self.clear_selection()
            self.notify("Copied", timeout=1)
            return
        asyncio.create_task(self.action_quit())

    async def action_quit(self) -> None:
        """Gracefully shut down, stopping service if running."""
        if self._service_mode and self._service is not None:
            try:
                await self._service.stop()
            except Exception:
                pass
        if self._service_task and not self._service_task.done():
            self._service_task.cancel()
        self.exit()

    def action_clear_chat(self) -> None:
        if self._agent:
            self._agent.reset()
        # Delete empty current session, start a new one
        if self._session_id:
            msgs = history.load_session(self._session_id)
            if not msgs:
                history.delete_session(self._session_id)
        self._session_id = history.create_session()
        self.query_one("#messages", VerticalScroll).remove_children()
        self._add_text("Conversation cleared.", "msg-status")

    def action_show_stats(self) -> None:
        if not self._agent:
            return
        stats = self._agent.get_token_stats()
        cost = _fmt_cost(stats.get("session_cost"))
        lines = [
            "**Token Statistics**\n",
            f"- Context: {stats['context_tokens']:,} tokens",
            f"- Messages: {stats['message_count']}",
            f"- Session input: {stats['session_input_tokens']:,}",
            f"- Session output: {stats['session_output_tokens']:,}",
            f"- Session total: {stats['session_total_tokens']:,}",
        ]
        if cost:
            lines.append(f"- Cost: {cost}")
        try:
            from macbot.usage import UsageTracker
            monthly = UsageTracker().get_monthly_summary()
            if monthly.get("interactions"):
                mc = _fmt_cost(monthly.get("cost"))
                lines.append(f"\n**Monthly ({datetime.now().strftime('%Y-%m')})**")
                lines.append(f"- Interactions: {monthly['interactions']:,}")
                lines.append(f"- Tokens: {monthly['input_tokens'] + monthly['output_tokens']:,}")
                if mc:
                    lines.append(f"- Cost: {mc}")
        except Exception:
            pass
        self._add_md("\n".join(lines))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_tokens(n: int) -> str:
    if n >= 10000:
        return f"{n / 1000:.1f}K"
    return str(n)


def _fmt_cost(cost: float | None) -> str:
    if cost is None or cost == 0:
        return ""
    if cost < 0.01:
        return f"${cost:.4f}"
    return f"${cost:.2f}"
