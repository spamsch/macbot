"""Unified macbot service.

Runs the cron scheduler and Telegram listener together as a single service.
"""

import asyncio
import base64
import json
import logging
import os
import signal
import stat
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from macbot.config import settings
from macbot.core.agent import Agent
from macbot.cron import CronPayload, CronService
from macbot.tasks import create_default_registry
from macbot.usage import UsageTracker

logger = logging.getLogger(__name__)

# Service paths
MACBOT_DIR = Path.home() / ".macbot"
PID_FILE = MACBOT_DIR / "service.pid"
LOG_FILE = MACBOT_DIR / "service.log"
HEARTBEAT_FILE = MACBOT_DIR / "heartbeat.md"
SOCKET_PATH = MACBOT_DIR / "session.sock"


@dataclass
class QueuedMessage:
    """A message waiting to be processed by the agent."""

    content: str | list[dict[str, Any]]  # str for text, list for multimodal content blocks
    emit: Callable[[dict], None] | None = None
    result_future: asyncio.Future = field(default_factory=lambda: asyncio.get_event_loop().create_future())


class AgentQueue:
    """Serializes agent.run() calls through an asyncio.Queue.

    This ensures only one agent.run() executes at a time, preventing
    interleaved message mutations when multiple clients (stdin, Telegram,
    socket) share the same Agent instance.
    """

    def __init__(self, agent: Agent, usage_tracker: UsageTracker | None = None) -> None:
        self.agent = agent
        self._queue: asyncio.Queue[QueuedMessage | None] = asyncio.Queue()
        self._running = False
        self._usage_tracker = usage_tracker or UsageTracker()

    async def submit(self, content: str | list[dict[str, Any]], emit: Callable[[dict], None] | None = None) -> str:
        """Enqueue a message and wait for the result.

        Args:
            content: The user message (str) or multimodal content blocks (list).
            emit: Optional callback for streaming events.

        Returns:
            The agent's text response.
        """
        loop = asyncio.get_event_loop()
        msg = QueuedMessage(content=content, emit=emit, result_future=loop.create_future())
        await self._queue.put(msg)
        return await msg.result_future

    async def run_consumer(self) -> None:
        """Process queued messages one at a time. Runs until stop() is called."""
        self._running = True
        while self._running:
            msg = await self._queue.get()
            if msg is None:
                # Poison pill — shut down
                break
            try:
                result = await self.agent.run(
                    msg.content,
                    stream=False,
                    continue_conversation=True,
                    on_event=msg.emit,
                )
                try:
                    self._usage_tracker.record(self.agent.get_interaction_cost())
                except Exception:
                    logger.debug("Failed to record usage", exc_info=True)
                if not msg.result_future.done():
                    msg.result_future.set_result(result)
            except Exception as e:
                if not msg.result_future.done():
                    msg.result_future.set_exception(e)
            finally:
                self._queue.task_done()

    def stop(self) -> None:
        """Signal the consumer to stop after current message completes."""
        self._running = False
        self._queue.put_nowait(None)


def get_service_pid() -> int | None:
    """Get the PID of a running macbot service, or None if not running."""
    if not PID_FILE.exists():
        return None
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        PID_FILE.unlink(missing_ok=True)
        return None


def stop_service() -> bool:
    """Stop the running macbot service.

    Returns:
        True if service was stopped, False if not running
    """
    pid = get_service_pid()
    if not pid:
        return False

    try:
        os.kill(pid, signal.SIGTERM)
        # Wait for process to exit
        import time
        for _ in range(20):
            time.sleep(0.2)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                PID_FILE.unlink(missing_ok=True)
                return True
        return True
    except ProcessLookupError:
        PID_FILE.unlink(missing_ok=True)
        return False


class MacbotService:
    """Unified service that runs cron jobs and listens for Telegram messages."""

    def __init__(self, stderr_console: bool = False):
        """Initialize the service.

        Args:
            stderr_console: If True, Rich console output goes to stderr
                           (keeps stdout clean for JSON-lines protocol in foreground mode).
        """
        from rich.console import Console
        self.registry = create_default_registry()
        self.agent = Agent(self.registry)  # Default agent for cron jobs
        self._chat_agents: dict[str, Agent] = {}  # Per-chat agents for Telegram conversations
        self._agent_queues: dict[str, AgentQueue] = {}  # Per-chat queues
        self._cron_queue: AgentQueue | None = None  # Queue for cron/heartbeat
        self._default_queue: AgentQueue | None = None  # Queue for stdin/socket
        self._console = Console(stderr=True) if stderr_console else Console()
        self.cron_service: CronService | None = None
        self.telegram_service = None
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._emit: Callable | None = None
        self._socket_server: asyncio.Server | None = None

    def reload_skills(self) -> None:
        """Reload skills from disk for all agents.

        Called via SIGHUP signal when skills are added/modified.
        """
        logger.info("Reloading skills...")

        # Reload the main agent's skills registry
        self.agent.skills_registry.reload()

        # Reload skills for all chat agents
        for chat_id, agent in self._chat_agents.items():
            agent.skills_registry.reload()
            logger.debug(f"Reloaded skills for chat {chat_id}")

        skill_count = len(self.agent.skills_registry)
        enabled_count = len(self.agent.skills_registry.list_enabled_skills())
        logger.info(f"Skills reloaded: {enabled_count}/{skill_count} enabled")

    def _get_chat_agent(self, chat_id: str) -> Agent:
        """Get or create an agent for a specific chat.

        Each chat gets its own agent instance to maintain conversation history.

        Args:
            chat_id: The Telegram chat ID

        Returns:
            Agent instance for this chat
        """
        if chat_id not in self._chat_agents:
            self._chat_agents[chat_id] = Agent(self.registry)
        return self._chat_agents[chat_id]

    def _get_agent_queue(self, chat_id: str) -> AgentQueue:
        """Get or create a queue for a specific chat agent.

        Args:
            chat_id: The Telegram chat ID

        Returns:
            AgentQueue wrapping the per-chat agent
        """
        if chat_id not in self._agent_queues:
            agent = self._get_chat_agent(chat_id)
            queue = AgentQueue(agent)
            self._agent_queues[chat_id] = queue
            # Start consumer task if service is running
            if self._running:
                self._tasks.append(asyncio.create_task(queue.run_consumer()))
        return self._agent_queues[chat_id]

    def _get_default_queue(self) -> AgentQueue:
        """Get the default queue shared by stdin/socket clients.

        Uses the primary Telegram chat agent if configured, else the
        default agent.

        Returns:
            AgentQueue for the default/shared agent
        """
        if self._default_queue is None:
            if settings.telegram_chat_id:
                agent = self._get_chat_agent(settings.telegram_chat_id)
            else:
                agent = self.agent
            self._default_queue = AgentQueue(agent)
        return self._default_queue

    def _save_chat_id(self, chat_id: str) -> None:
        """Auto-save a detected Telegram chat ID to the config file.

        Called on the first incoming message when MACBOT_TELEGRAM_CHAT_ID
        is not set, so the user doesn't have to configure it manually.
        """
        env_file = Path.home() / ".macbot" / ".env"
        try:
            if env_file.exists():
                content = env_file.read_text()
            else:
                content = ""

            # Don't duplicate if already present
            if f"MACBOT_TELEGRAM_CHAT_ID={chat_id}" in content:
                return

            # Remove any existing (empty) chat ID line
            lines = [l for l in content.splitlines()
                     if not l.strip().startswith("MACBOT_TELEGRAM_CHAT_ID=")]
            lines.append(f"MACBOT_TELEGRAM_CHAT_ID={chat_id}")
            env_file.write_text("\n".join(lines) + "\n")

            # Update in-memory settings
            settings.telegram_chat_id = chat_id
            self.telegram_service.default_chat_id = chat_id

            self._console.print(f"  ✓ Auto-saved Telegram chat ID: {chat_id}")
            logger.info(f"Auto-saved MACBOT_TELEGRAM_CHAT_ID={chat_id}")
        except Exception as e:
            logger.error(f"Failed to auto-save chat ID: {e}")

    async def _detect_chat_id_at_startup(self) -> None:
        """Try to detect chat ID from pending Telegram messages at startup.

        Does a quick non-blocking poll. If the user previously sent a message
        to the bot (e.g. during onboarding), we pick up the chat ID without
        requiring them to send another message.
        """
        try:
            from macbot.telegram import TelegramBot
            bot = TelegramBot(settings.telegram_bot_token)
            updates = await bot.get_updates(offset=None, timeout=0)
            await bot.close()

            for update in updates:
                if update.message:
                    chat_id = str(update.message.chat_id)
                    self._save_chat_id(chat_id)
                    return
        except Exception as e:
            logger.debug(f"Chat ID startup detection failed (non-fatal): {e}")

    def _setup_cron(self) -> bool:
        """Set up the cron service.

        Returns:
            True if cron has enabled jobs, False otherwise
        """
        self.cron_service = CronService(storage_path=settings.get_cron_storage_path())
        jobs = self.cron_service.list_jobs()
        enabled_jobs = [j for j in jobs if j.enabled]

        if not enabled_jobs:
            return False

        async def agent_handler(payload: CronPayload):
            from macbot.cron.executor import ExecutionResult
            try:
                timestamp = datetime.now().strftime("%H:%M:%S")
                # Show cron job in console
                self._console.print(f"\n[{timestamp}] ⏰ Cron: {payload.message[:100]}{'...' if len(payload.message) > 100 else ''}")
                logger.info(f"Cron: Running '{payload.message[:50]}...'")
                result = await self._cron_queue.submit(payload.message)
                logger.info(f"Cron: Completed, result length: {len(result)}")
                return ExecutionResult(success=True, output=result)
            except Exception as e:
                logger.error(f"Cron: Error - {e}")
                return ExecutionResult(success=False, error=str(e))

        self.cron_service.set_agent_handler(agent_handler)
        return True

    def _setup_telegram(self) -> bool:
        """Set up the Telegram service.

        Returns:
            True if Telegram is configured, False otherwise
        """
        if not settings.telegram_bot_token:
            return False

        from macbot.telegram import TelegramService

        self.telegram_service = TelegramService(
            bot_token=settings.telegram_bot_token,
            chat_id=settings.telegram_chat_id or None,
            allowed_users=settings.telegram_allowed_users or None,
        )

        async def message_handler(content: str | list[dict[str, Any]], chat_id: str) -> str:
            from datetime import datetime
            timestamp = datetime.now().strftime("%H:%M:%S")
            # Extract text preview for logging
            if isinstance(content, str):
                preview = content[:100]
            else:
                # Multimodal: extract text block for preview
                text_parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
                preview = (text_parts[0] if text_parts else "[image]")[:100]
            # Show incoming message in console
            self._console.print(f"\n[{timestamp}] 📩 Telegram: {preview}{'...' if len(preview) >= 100 else ''}")
            logger.info(f"Telegram: Message from {chat_id}: {preview[:50]}...")

            # Emit incoming message to GUI (include image URL if present)
            if self._emit:
                event: dict[str, Any] = {"type": "telegram_message", "text": preview, "chat_id": chat_id, "direction": "incoming"}
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "image_url":
                            event["imageUrl"] = block["image_url"]["url"]
                            break
                self._emit(event)

            # Auto-detect chat ID if not configured
            if not settings.telegram_chat_id:
                self._save_chat_id(chat_id)

            # Handle special commands (only for plain text)
            if isinstance(content, str) and content.strip().lower() in ("/reset", "/clear", "/new"):
                if chat_id in self._chat_agents:
                    self._chat_agents[chat_id].reset()
                reply = "Conversation cleared. Starting fresh!"
                if self._emit:
                    self._emit({"type": "telegram_message", "text": reply, "chat_id": chat_id, "direction": "outgoing"})
                return reply

            # Send acknowledgment
            await self.telegram_service.send_message("⏳ Working on it...", chat_id, parse_mode=None)

            try:
                # Build a combined emit that forwards to both GUI and Telegram progress
                tools_called: list[str] = []

                def _combined_emit(obj: dict) -> None:
                    # Forward to GUI
                    if self._emit:
                        self._emit(obj)
                    # Track tool calls for Telegram progress
                    if obj.get("type") == "tool_call":
                        tools_called.append(obj.get("name", "?"))
                        count = len(tools_called)
                        name = obj.get("name", "?")
                        if count == 1:
                            asyncio.get_event_loop().create_task(
                                self.telegram_service.send_message(
                                    f"🔧 `{name}`...", chat_id, parse_mode="Markdown"
                                )
                            )
                        elif count % 3 == 0:
                            asyncio.get_event_loop().create_task(
                                self.telegram_service.send_message(
                                    f"🔧 `{name}` ({count} steps)...", chat_id, parse_mode="Markdown"
                                )
                            )

                queue = self._get_agent_queue(chat_id)
                result = await queue.submit(content, emit=_combined_emit)

                # Emit outgoing response to GUI
                if self._emit:
                    self._emit({"type": "telegram_message", "text": result, "chat_id": chat_id, "direction": "outgoing"})

                # Show response in terminal as rendered markdown
                from rich.markdown import Markdown
                from rich.panel import Panel
                timestamp = datetime.now().strftime("%H:%M:%S")
                self._console.print(Panel(
                    Markdown(result),
                    title=f"[dim]{timestamp}[/dim] 🤖 Response",
                    border_style="green",
                    padding=(0, 1),
                ))

                logger.info(f"Telegram: Response sent, length: {len(result)}, tools: {len(tools_called)}")
                return result
            except Exception as e:
                logger.error(f"Telegram: Error - {e}")
                error_msg = f"Error: {e}"
                if self._emit:
                    self._emit({"type": "telegram_message", "text": error_msg, "chat_id": chat_id, "direction": "outgoing"})
                return error_msg

        self.telegram_service.set_message_handler(message_handler)
        return True

    async def _run_cron(self) -> None:
        """Run the cron service loop."""
        if not self.cron_service:
            return
        await self.cron_service.start()
        while self._running:
            await asyncio.sleep(1)

    async def _run_telegram(self) -> None:
        """Run the Telegram service loop."""
        if not self.telegram_service:
            return
        await self.telegram_service.start()

    async def _run_heartbeat(self) -> None:
        """Run the heartbeat loop at the configured interval.

        Reads ~/.macbot/heartbeat.md and executes its content as a prompt.
        If the file doesn't exist or is empty, just prints 'heartbeat'.
        Only runs during active hours to save API costs.
        """
        while self._running:
            try:
                await asyncio.sleep(settings.heartbeat_interval)
            except asyncio.CancelledError:
                return

            now = datetime.now()
            timestamp = now.strftime("%H:%M:%S")

            # Skip outside active hours
            if not (settings.heartbeat_active_start <= now.hour < settings.heartbeat_active_end):
                logger.debug(f"Heartbeat: Skipping outside active hours ({settings.heartbeat_active_start}:00-{settings.heartbeat_active_end}:00)")
                continue

            try:
                if HEARTBEAT_FILE.exists():
                    content = HEARTBEAT_FILE.read_text().strip()
                else:
                    content = ""

                if not content:
                    self._console.print(f"[{timestamp}] heartbeat")
                    continue

                self._console.print(f"\n[{timestamp}] 💓 Heartbeat: {content[:100]}{'...' if len(content) > 100 else ''}")
                logger.info(f"Heartbeat: Running '{content[:50]}...'")
                result = await self._cron_queue.submit(content)
                logger.info(f"Heartbeat: Completed, result length: {len(result)}")
                from rich.markdown import Markdown
                from rich.panel import Panel
                self._console.print(Panel(
                    Markdown(result),
                    title=f"[dim]{timestamp}[/dim] 💓 Heartbeat",
                    border_style="magenta",
                    padding=(0, 1),
                ))

                # Send result to Telegram if configured
                if self.telegram_service and result:
                    try:
                        chat_id = settings.telegram_chat_id
                        if chat_id:
                            await self.telegram_service.send_message(result, chat_id)
                    except Exception as e:
                        logger.warning(f"Heartbeat: Failed to send to Telegram: {e}")
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.error(f"Heartbeat: Error - {e}")
                self._console.print(f"[{timestamp}] 💓 Heartbeat error: {e}")

    def _format_tokens(self, count: int) -> str:
        """Format token count with K suffix for thousands."""
        if count >= 1000:
            return f"{count / 1000:.1f}K"
        return str(count)

    @staticmethod
    def _format_cost(cost: float | None) -> str:
        """Format a dollar cost, or return empty string if unknown."""
        if not cost:
            return ""
        if cost < 0.01:
            return f"${cost:.4f}"
        return f"${cost:.2f}"

    async def _transcribe_audio(self, audio_b64: str, audio_format: str) -> str:
        """Decode base64 audio and transcribe via OpenAI Whisper.

        Args:
            audio_b64: Base64-encoded audio data.
            audio_format: Audio format extension (e.g. "webm", "ogg").

        Returns:
            Transcribed text.

        Raises:
            ValueError: If OpenAI API key is not configured.
            Exception: On transcription failure.
        """
        if not settings.openai_api_key:
            raise ValueError("OpenAI API key not configured — cannot transcribe audio")

        audio_bytes = base64.b64decode(audio_b64)

        with tempfile.NamedTemporaryFile(suffix=f".{audio_format}", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(audio_bytes)

        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=settings.openai_api_key)
            with open(tmp_path, "rb") as audio_file:
                transcript = await client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                )
            return transcript.text
        finally:
            tmp_path.unlink(missing_ok=True)

    def _print_context(self, agent: Agent, console: "Console") -> None:
        """Print a formatted overview of the current agent context."""
        from rich.panel import Panel
        from rich.table import Table
        from rich.tree import Tree

        stats = agent.get_token_stats()

        # Build context tree
        tree = Tree("[bold]Agent Context[/bold]")

        # Model & provider
        model_branch = tree.add("[bold cyan]Model[/bold cyan]")
        model_branch.add(f"{agent.config.get_model()}")

        # Token stats
        tokens_branch = tree.add("[bold cyan]Tokens[/bold cyan]")
        tokens_branch.add(f"Context: {stats['context_tokens']:,}")
        cost_str = self._format_cost(stats.get("session_cost"))
        cost_part = f", cost: {cost_str}" if cost_str else ""
        tokens_branch.add(f"Session: {stats['session_total_tokens']:,} (in: {stats['session_input_tokens']:,}, out: {stats['session_output_tokens']:,}{cost_part})")

        # Conversation messages
        msg_branch = tree.add(f"[bold cyan]Messages[/bold cyan] ({stats['message_count']})")
        for msg in agent.messages:
            role = msg.role
            if role == "user":
                text = msg.content_text
                preview = text[:80]
                suffix = " [image]" if isinstance(msg.content, list) else ""
                msg_branch.add(f"[green]user[/green]: {preview}{'...' if len(text) > 80 else ''}{suffix}")
            elif role == "assistant":
                if msg.tool_calls:
                    tools = ", ".join(tc.name for tc in msg.tool_calls)
                    msg_branch.add(f"[blue]assistant[/blue]: [dim]tool calls:[/dim] {tools}")
                else:
                    text = msg.content_text
                    preview = text[:80]
                    msg_branch.add(f"[blue]assistant[/blue]: {preview}{'...' if len(text) > 80 else ''}")
            elif role == "tool":
                text = msg.content_text
                preview = text[:60]
                msg_branch.add(f"[yellow]tool[/yellow]: {preview}{'...' if len(text) > 60 else ''}")

        # Skills
        enabled_skills = agent.skills_registry.list_enabled_skills()
        skills_branch = tree.add(f"[bold cyan]Skills[/bold cyan] ({len(enabled_skills)} enabled)")
        for skill in sorted(enabled_skills, key=lambda s: s.name):
            skill_node = skills_branch.add(f"[green]{skill.name}[/green] [dim]({skill.id})[/dim]")
            if skill.tasks:
                skill_node.add(f"[dim]Tools: {', '.join(skill.tasks)}[/dim]")
            if skill.apps:
                skill_node.add(f"[dim]Apps: {', '.join(skill.apps)}[/dim]")

        # Tools (from task registry)
        all_tasks = list(agent.task_registry._tasks.keys())
        tools_branch = tree.add(f"[bold cyan]Tools[/bold cyan] ({len(all_tasks)} registered)")
        # Group by prefix
        groups: dict[str, list[str]] = {}
        for t in sorted(all_tasks):
            prefix = t.split("_")[0] if "_" in t else t
            groups.setdefault(prefix, []).append(t)
        for prefix, tasks in sorted(groups.items()):
            if len(tasks) == 1:
                tools_branch.add(f"[dim]{tasks[0]}[/dim]")
            else:
                group_node = tools_branch.add(f"[dim]{prefix}[/dim] ({len(tasks)})")
                for t in tasks:
                    group_node.add(f"[dim]{t}[/dim]")

        console.print()
        console.print(tree)
        console.print()

    async def _run_stdin_reader(self) -> None:
        """Run stdin reader for GUI/foreground mode using JSON-lines protocol.

        Input (stdin):  {"type": "message", "text": "..."}
        Output (stdout): {"type": "ready"}
                         {"type": "tool_call", "name": "...", "arguments": {...}}
                         {"type": "tool_result", "success": true/false, ...}
                         {"type": "chunk", "text": "..."}
                         {"type": "done"}
                         {"type": "error", "text": "..."}
        """
        import sys
        from concurrent.futures import ThreadPoolExecutor

        executor = ThreadPoolExecutor(max_workers=1)
        loop = asyncio.get_event_loop()

        queue = self._get_default_queue()

        def _emit(obj: dict) -> None:
            sys.stdout.write(json.dumps(obj) + "\n")
            sys.stdout.flush()

        self._emit = _emit

        def read_line():
            try:
                return sys.stdin.readline()
            except Exception:
                return None

        _emit({"type": "ready"})

        while self._running:
            try:
                raw = await loop.run_in_executor(executor, read_line)

                if raw is None or raw == "":
                    # EOF — stdin closed (Tauri app quit)
                    logger.info("Stdin closed (EOF), initiating shutdown")
                    await self.stop()
                    break

                raw = raw.strip()
                if not raw:
                    continue

                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    _emit({"type": "error", "text": "Invalid JSON input"})
                    continue

                msg_type = msg.get("type")

                if msg_type == "audio_message":
                    # Voice-to-text: transcribe then process as normal message
                    audio_b64 = msg.get("audio", "")
                    audio_format = msg.get("format", "webm")
                    if not audio_b64:
                        _emit({"type": "error", "text": "Empty audio data"})
                        continue
                    try:
                        text = await self._transcribe_audio(audio_b64, audio_format)
                        _emit({"type": "transcription", "text": text})
                    except Exception as e:
                        _emit({"type": "error", "text": f"Transcription failed: {e}"})
                        _emit({"type": "done"})
                        continue
                    # Fall through to submit transcribed text to agent
                elif msg_type == "message":
                    text = msg.get("text", "").strip()
                    if not text:
                        _emit({"type": "error", "text": "Empty message"})
                        continue
                else:
                    _emit({"type": "error", "text": f"Unknown message type: {msg_type}"})
                    continue

                try:
                    result = await queue.submit(text, emit=_emit)
                    _emit({"type": "chunk", "text": result})
                except Exception as e:
                    _emit({"type": "error", "text": str(e)})

                _emit({
                    "type": "done",
                    **queue.agent.get_interaction_cost(),
                    "monthly": queue._usage_tracker.get_monthly_summary(),
                })

            except EOFError:
                break
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Stdin reader error: {e}")
                await asyncio.sleep(0.1)

        executor.shutdown(wait=False)

    async def _run_interactive(self) -> None:
        """Run interactive console input loop with readline support."""
        import readline
        from concurrent.futures import ThreadPoolExecutor
        from rich.console import Console
        from rich.markdown import Markdown

        # Set up readline with persistent history
        history_file = MACBOT_DIR / "input_history"
        try:
            readline.read_history_file(history_file)
        except FileNotFoundError:
            pass
        readline.set_history_length(500)

        executor = ThreadPoolExecutor(max_workers=1)
        loop = asyncio.get_event_loop()
        console = Console()

        queue = self._get_default_queue()
        agent = queue.agent

        if settings.telegram_chat_id:
            console.print(f"\n[dim][Context shared with Telegram chat {settings.telegram_chat_id}][/dim]")

        console.print("[dim][Ready for input - type a query or 'quit' to exit][/dim]")
        console.print("[dim][Commands: 'clear' resets conversation, 'stats' shows tokens, 'context' shows structure][/dim]\n")

        while self._running:
            try:
                # Build prompt with token stats and cost
                stats = agent.get_token_stats()
                ctx = self._format_tokens(stats["context_tokens"])
                total = self._format_tokens(stats["session_total_tokens"])

                if stats["session_total_tokens"] > 0:
                    cost_str = self._format_cost(stats.get("session_cost"))
                    cost_part = f" {cost_str}" if cost_str else ""
                    prompt = f"\x1b[2m(ctx:{ctx} total:{total}{cost_part})\x1b[0m \x1b[1;34m→\x1b[0m "
                else:
                    prompt = "\x1b[1;34m→\x1b[0m "

                # Use input() instead of console.input() for readline support
                user_input = await loop.run_in_executor(
                    executor, lambda p=prompt: input(p).strip()
                )

                if not user_input:
                    continue

                if user_input.lower() in ("quit", "exit", "q"):
                    # Show final stats
                    stats = agent.get_token_stats()
                    if stats["session_total_tokens"] > 0:
                        cost_str = self._format_cost(stats.get("session_cost"))
                        cost_part = f", cost: {cost_str}" if cost_str else ""
                        console.print(f"\n[dim]Session total: {stats['session_total_tokens']:,} tokens "
                                      f"(in: {stats['session_input_tokens']:,}, out: {stats['session_output_tokens']:,}{cost_part})[/dim]")
                    console.print("[dim][Stopping service...][/dim]")
                    readline.write_history_file(history_file)
                    await self.stop()
                    break

                if user_input.lower() == "clear":
                    agent.reset()
                    console.print("[dim][Conversation cleared - token session continues][/dim]")
                    continue

                if user_input.lower() == "stats":
                    stats = agent.get_token_stats()
                    cost_str = self._format_cost(stats.get("session_cost"))
                    console.print(f"\n[bold]Token Statistics[/bold]")
                    console.print(f"  Context size:    {stats['context_tokens']:,} tokens")
                    console.print(f"  Messages:        {stats['message_count']}")
                    console.print(f"  Session input:   {stats['session_input_tokens']:,} tokens")
                    console.print(f"  Session output:  {stats['session_output_tokens']:,} tokens")
                    console.print(f"  Session total:   {stats['session_total_tokens']:,} tokens")
                    if cost_str:
                        console.print(f"  Session cost:    {cost_str}")
                    console.print()
                    continue

                if user_input.lower() == "context":
                    self._print_context(agent, console)
                    continue

                # Process query through shared agent (cancellable with Escape)
                timestamp = datetime.now().strftime("%H:%M:%S")
                console.print(f"[dim][{timestamp}] Processing... (Escape to cancel)[/dim]\n")

                try:
                    from macbot.utils.cancellable import run_with_escape_cancel

                    result, cancelled = await run_with_escape_cancel(
                        queue.submit(user_input)
                    )

                    if cancelled:
                        console.print("\n[dim][Cancelled by Escape][/dim]\n")
                    else:
                        console.print()
                        console.print("[bold green]A:[/bold green]", end=" ")
                        console.print(Markdown(result))
                        console.print("[dim]─" * 60 + "[/dim]\n")
                except Exception as e:
                    console.print(f"\n[red]Error: {e}[/red]\n")

            except EOFError:
                readline.write_history_file(history_file)
                break
            except asyncio.CancelledError:
                readline.write_history_file(history_file)
                break

        executor.shutdown(wait=False)

    async def _run_socket_server(self) -> None:
        """Run a Unix domain socket server for external client connections.

        Accepts connections from `son connect` and speaks the same JSON-lines
        protocol as the stdin reader.
        """
        # Clean up stale socket
        SOCKET_PATH.unlink(missing_ok=True)

        self._socket_server = await asyncio.start_unix_server(
            self._handle_socket_client,
            path=str(SOCKET_PATH),
        )
        # Restrict permissions to owner only
        os.chmod(SOCKET_PATH, stat.S_IRUSR | stat.S_IWUSR)
        logger.info(f"Socket server listening at {SOCKET_PATH}")

        try:
            await self._socket_server.serve_forever()
        except asyncio.CancelledError:
            pass
        finally:
            self._socket_server.close()
            SOCKET_PATH.unlink(missing_ok=True)

    async def _handle_socket_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle a single socket client connection.

        Speaks the same JSON-lines protocol as _run_stdin_reader.
        """
        peer = writer.get_extra_info("peername") or "unknown"
        logger.info(f"Socket client connected: {peer}")

        queue = self._get_default_queue()

        def _emit(obj: dict) -> None:
            try:
                data = json.dumps(obj) + "\n"
                writer.write(data.encode())
            except Exception:
                pass  # Client may have disconnected

        try:
            _emit({"type": "ready"})
            await writer.drain()

            while self._running:
                raw_bytes = await reader.readline()
                if not raw_bytes:
                    # Client disconnected
                    break

                raw = raw_bytes.decode().strip()
                if not raw:
                    continue

                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    _emit({"type": "error", "text": "Invalid JSON input"})
                    await writer.drain()
                    continue

                if msg.get("type") != "message":
                    _emit({"type": "error", "text": f"Unknown message type: {msg.get('type')}"})
                    await writer.drain()
                    continue

                text = msg.get("text", "").strip()
                if not text:
                    _emit({"type": "error", "text": "Empty message"})
                    await writer.drain()
                    continue

                try:
                    result = await queue.submit(text, emit=_emit)
                    _emit({"type": "chunk", "text": result})
                except Exception as e:
                    _emit({"type": "error", "text": str(e)})

                _emit({
                    "type": "done",
                    **queue.agent.get_interaction_cost(),
                    "monthly": queue._usage_tracker.get_monthly_summary(),
                })
                await writer.drain()

        except (ConnectionResetError, BrokenPipeError):
            logger.debug(f"Socket client disconnected: {peer}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Socket client error: {e}")
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            logger.info(f"Socket client disconnected: {peer}")

    async def _stop_socket_server(self) -> None:
        """Stop the socket server and clean up."""
        if self._socket_server:
            self._socket_server.close()
            await self._socket_server.wait_closed()
            self._socket_server = None
        SOCKET_PATH.unlink(missing_ok=True)

    async def start(self, interactive: bool = False, stdin_reader: bool = False) -> None:
        """Start all configured services.

        Args:
            interactive: Whether to also run an interactive input loop (CLI mode)
            stdin_reader: Whether to read queries from stdin (GUI/foreground mode)
        """
        self._running = True

        # Set up SIGHUP handler for skills reload
        loop = asyncio.get_event_loop()
        loop.add_signal_handler(signal.SIGHUP, self.reload_skills)
        logger.debug("SIGHUP handler registered for skills reload")

        has_cron = self._setup_cron()
        has_telegram = self._setup_telegram()

        # Initialize cron queue (shared by cron jobs and heartbeat)
        self._cron_queue = AgentQueue(self.agent)
        self._tasks.append(asyncio.create_task(self._cron_queue.run_consumer()))

        # Initialize default queue (shared by stdin/socket/interactive)
        default_queue = self._get_default_queue()
        self._tasks.append(asyncio.create_task(default_queue.run_consumer()))

        # Heartbeat always runs
        logger.info(f"Starting heartbeat (every {settings.heartbeat_interval}s)")
        self._tasks.append(asyncio.create_task(self._run_heartbeat()))

        if has_cron:
            jobs = [j for j in self.cron_service.list_jobs() if j.enabled]
            logger.info(f"Starting cron service with {len(jobs)} enabled jobs")
            self._tasks.append(asyncio.create_task(self._run_cron()))

        if has_telegram:
            from macbot.telegram.bot import validate_token
            ok, msg = await validate_token(settings.telegram_bot_token)
            if ok:
                logger.info(f"Starting Telegram service as {msg}")

                # Auto-detect chat ID from pending messages if not configured
                if not settings.telegram_chat_id:
                    await self._detect_chat_id_at_startup()

                self._tasks.append(asyncio.create_task(self._run_telegram()))
            else:
                logger.error(f"Telegram token invalid: {msg}")

        # Always start socket server for `son connect`
        MACBOT_DIR.mkdir(parents=True, exist_ok=True)
        self._tasks.append(asyncio.create_task(self._run_socket_server()))

        # Add interactive loop if requested (CLI mode)
        if interactive:
            self._tasks.append(asyncio.create_task(self._run_interactive()))
        # Add stdin reader for GUI/foreground mode
        elif stdin_reader:
            self._tasks.append(asyncio.create_task(self._run_stdin_reader()))
        elif not self._tasks:
            logger.warning("No services configured (no cron jobs, no Telegram)")
            return

        # Wait for all tasks
        try:
            await asyncio.gather(*self._tasks)
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        """Stop all services gracefully."""
        self._running = False

        # Stop socket server
        await self._stop_socket_server()

        # Stop all queues
        if self._cron_queue:
            self._cron_queue.stop()
        if self._default_queue:
            self._default_queue.stop()
        for q in self._agent_queues.values():
            q.stop()

        if self.telegram_service:
            await self.telegram_service.stop()

        if self.cron_service:
            await self.cron_service.stop()

        for task in self._tasks:
            task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    def get_status(self) -> dict:
        """Get status of all services.

        Returns:
            Dictionary with service status information
        """
        status = {
            "running": self._running,
            "cron": {
                "enabled": False,
                "jobs_total": 0,
                "jobs_enabled": 0,
            },
            "telegram": {
                "enabled": False,
                "connected": False,
                "bot_username": None,
            },
        }

        # Cron status
        cron_service = CronService(storage_path=settings.get_cron_storage_path())
        jobs = cron_service.list_jobs()
        enabled_jobs = [j for j in jobs if j.enabled]
        status["cron"]["jobs_total"] = len(jobs)
        status["cron"]["jobs_enabled"] = len(enabled_jobs)
        status["cron"]["enabled"] = len(enabled_jobs) > 0

        # Telegram status
        if settings.telegram_bot_token:
            status["telegram"]["enabled"] = True
            status["telegram"]["chat_id"] = settings.telegram_chat_id or None

        return status


def run_service(daemon: bool = False, verbose: bool = False, foreground: bool = False) -> None:
    """Run the macbot service.

    Args:
        daemon: Whether to run as a background daemon
        verbose: Whether to show verbose output
        foreground: Whether to run in foreground without interactive console (for GUI)
    """
    from rich.console import Console
    # In foreground mode, use stderr for all Rich output to keep stdout clean for JSON-lines
    console = Console(stderr=True) if foreground else Console()

    # Check what's available
    service = MacbotService(stderr_console=foreground)
    status = service.get_status()

    has_cron = status["cron"]["enabled"]
    has_telegram = status["telegram"]["enabled"]

    # Show what will run
    from macbot import __version__
    console.print(f"[bold]Starting Son of Simon[/bold] v{__version__}...\n")

    # Show model/provider
    model = settings.get_model()
    provider = settings.get_provider()
    if provider == "pico":
        api_base = settings.pico_api_base
        model_name = model.split("/", 1)[1] if "/" in model else model
        console.print(f"  [green]✓[/green] Model: {model_name} via Pico ({api_base})")
    else:
        console.print(f"  [green]✓[/green] Model: {model}")

    console.print(f"  [green]✓[/green] Heartbeat: every {settings.heartbeat_interval // 60} minutes, {settings.heartbeat_active_start}:00-{settings.heartbeat_active_end}:00 (~/.macbot/heartbeat.md)")

    if has_cron:
        console.print(f"  [green]✓[/green] Scheduled Tasks: {status['cron']['jobs_enabled']} active")
    else:
        console.print(f"  [dim]○[/dim] Scheduled Tasks: None configured")

    if has_telegram:
        chat_info = f" (chat: {status['telegram']['chat_id']})" if status['telegram'].get('chat_id') else ""
        console.print(f"  [green]✓[/green] Telegram: Connected{chat_info}")
        if not status['telegram'].get('chat_id'):
            console.print(f"  [yellow]![/yellow] Chat ID not set — send any message to your bot on Telegram to link it automatically")
    else:
        console.print(f"  [dim]○[/dim] Telegram: Not connected")

    console.print()

    if daemon:
        # Check if already running
        existing_pid = get_service_pid()
        if existing_pid:
            console.print(f"[yellow]Service already running[/yellow] (PID {existing_pid})")
            console.print("Stop it first with: macbot stop")
            return

        console.print(f"[green]Starting in background...[/green]")
        console.print(f"  Log: {LOG_FILE}")
        console.print(f"\nUse 'macbot stop' to stop")

        # Daemonize
        _daemonize()

        # Now in daemon process
        _run_daemon_service()
    else:
        # Foreground mode
        if foreground:
            # Non-interactive foreground mode (for GUI integration)
            # Use stderr for Rich output so stdout stays clean for JSON-lines protocol
            from rich.console import Console as RichConsole
            stderr_console = RichConsole(stderr=True)

            logging.basicConfig(
                level=logging.INFO if verbose else logging.WARNING,
                format="%(asctime)s %(message)s",
                datefmt="%H:%M:%S",
                stream=__import__("sys").stderr,
            )

            # Write PID file as safety net for cleanup
            MACBOT_DIR.mkdir(parents=True, exist_ok=True)
            PID_FILE.write_text(str(os.getpid()))

            stderr_console.print("[green]✓[/green] Ready! You can now send commands.")

            try:
                # Enable stdin reader so GUI can send queries via JSON-lines
                asyncio.run(service.start(interactive=False, stdin_reader=True))
            except KeyboardInterrupt:
                stderr_console.print("\n[dim]Stopping...[/dim]")
                asyncio.run(service.stop())
            finally:
                PID_FILE.unlink(missing_ok=True)
            stderr_console.print("[dim]Service stopped.[/dim]")
        else:
            # Interactive mode with input prompt
            console.print("[dim]Type queries below, or 'quit' to exit. Ctrl+C also stops.[/dim]")

            # Set up logging for foreground
            if verbose:
                logging.basicConfig(
                    level=logging.INFO,
                    format="%(asctime)s [%(name)s] %(message)s",
                    datefmt="%H:%M:%S",
                )

            try:
                asyncio.run(service.start(interactive=True))
            except KeyboardInterrupt:
                console.print("\n[dim]Stopping...[/dim]")
                asyncio.run(service.stop())
                # Close stdin to unblock any thread still waiting on console.input()
                import sys
                try:
                    sys.stdin.close()
                except Exception:
                    pass
            console.print("[dim]Service stopped.[/dim]")


def _daemonize() -> None:
    """Fork the process to run in the background."""
    import sys

    # First fork
    pid = os.fork()
    if pid > 0:
        sys.exit(0)

    os.chdir("/")
    os.setsid()
    os.umask(0)

    # Second fork
    pid = os.fork()
    if pid > 0:
        sys.exit(0)

    # Redirect file descriptors
    sys.stdout.flush()
    sys.stderr.flush()

    MACBOT_DIR.mkdir(parents=True, exist_ok=True)
    log_fd = os.open(str(LOG_FILE), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    null_fd = os.open(os.devnull, os.O_RDONLY)

    os.dup2(null_fd, sys.stdin.fileno())
    os.dup2(log_fd, sys.stdout.fileno())
    os.dup2(log_fd, sys.stderr.fileno())

    os.close(null_fd)
    os.close(log_fd)

    # Write PID file
    PID_FILE.write_text(str(os.getpid()))


def _run_daemon_service() -> None:
    """Run the service in daemon mode."""
    import sys

    print(f"\n{'='*60}")
    print(f"MacBot Service started at {datetime.now().isoformat()}")
    print(f"PID: {os.getpid()}")
    print(f"{'='*60}\n")

    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Set up signal handler
    def handle_signal(signum, frame):
        print(f"\nReceived signal {signum}, shutting down...")
        PID_FILE.unlink(missing_ok=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    service = MacbotService()

    try:
        asyncio.run(service.start())
    except Exception as e:
        print(f"Service error: {e}")
    finally:
        PID_FILE.unlink(missing_ok=True)
