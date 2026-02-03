"""Command-line interface for MacBot.

MacBot is an LLM-powered agent that can execute tasks to achieve goals.

CONCEPTS:
---------
- TASK: A single executable action (e.g., get_unread_emails, create_reminder).
        Tasks are tools the agent can use. No LLM reasoning involved.

- GOAL: A natural language objective (e.g., "Check my emails").
        The agent uses LLM reasoning to decide which tasks to call.

- CHAT: Interactive conversation mode where you can have an ongoing
        dialogue with the agent, with context preserved between messages.

- JOB:  A goal or task scheduled to run automatically at intervals
        or specific times (cron). Used for automation.
"""

import argparse
import asyncio
import logging
import os
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import NoReturn

import yaml
from rich.console import Console
from rich.logging import RichHandler
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from macbot import __version__
from macbot.config import settings
from macbot.core.agent import Agent
from macbot.core.scheduler import ScheduledJob, TaskScheduler
from macbot.cron import (
    CronJobCreate,
    CronPayload,
    CronSchedule,
    CronService,
    ScheduleKind,
)
from macbot.tasks import create_default_registry

console = Console()

# Paths for daemon management
MACBOT_DIR = Path.home() / ".macbot"
PID_FILE = MACBOT_DIR / "scheduler.pid"
LOG_FILE = MACBOT_DIR / "scheduler.log"
JOBS_FILE = MACBOT_DIR / "jobs.yaml"


def load_jobs_from_file(jobs_file: Path | None = None) -> dict[str, str]:
    """Load jobs from a YAML file and return a dict of name -> goal.

    Args:
        jobs_file: Path to jobs YAML file. Defaults to ~/.macbot/jobs.yaml

    Returns:
        Dictionary mapping job names to their goals
    """
    if jobs_file is None:
        jobs_file = JOBS_FILE

    if not jobs_file.exists():
        return {}

    try:
        with open(jobs_file) as f:
            data = yaml.safe_load(f)

        if not data or "jobs" not in data:
            return {}

        jobs = {}
        for job in data["jobs"]:
            if "name" in job and "goal" in job:
                jobs[job["name"].lower()] = job["goal"]
        return jobs
    except Exception:
        return {}


def find_job_goal(name: str, jobs_file: Path | None = None) -> str | None:
    """Find a job's goal by name (case-insensitive).

    Args:
        name: Job name to search for
        jobs_file: Path to jobs YAML file

    Returns:
        The job's goal if found, None otherwise
    """
    jobs = load_jobs_from_file(jobs_file)
    return jobs.get(name.lower())

# Help text shown when no command is given
WELCOME_TEXT = f"""
# MacBot v{__version__}

An LLM-powered agent for macOS automation.

## Quick Start

```bash
macbot run "Check my emails"             # Run a goal
macbot run "What's on my calendar?"      # Ask a question
macbot start                             # Start service (cron + telegram)
macbot status                            # Check service status
macbot doctor                            # Verify setup
```

## Service Setup

1. Import scheduled jobs: `macbot cron import jobs.yaml`
2. Configure Telegram: `export MACBOT_TELEGRAM_BOT_TOKEN=...`
3. Start the service: `macbot start -d` (daemon) or `macbot start` (foreground)

Use `macbot --help-all` to see all commands including admin tools.
"""


def setup_logging(verbose: bool = False) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.WARNING
    fmt = "%(name)s: %(message)s" if verbose else "%(message)s"
    logging.basicConfig(
        level=level,
        format=fmt,
        handlers=[RichHandler(rich_tracebacks=True, console=console, show_path=verbose)],
    )


async def interactive_loop(agent: Agent, verbose: bool = False) -> None:
    """Run an interactive chat loop with the agent.

    Args:
        agent: The agent instance (may already have conversation history)
        verbose: Whether to show verbose output
    """
    console.print("\n[dim]Type your message, or 'quit' to exit. Use 'clear' to reset conversation.[/dim]\n")

    while True:
        try:
            # Get user input
            user_input = console.input("[bold blue]You:[/bold blue] ").strip()

            if not user_input:
                continue

            # Handle special commands
            if user_input.lower() in ("quit", "exit", "q"):
                console.print("[dim]Goodbye![/dim]")
                break

            if user_input.lower() == "clear":
                agent.reset()
                console.print("[dim]Conversation cleared.[/dim]\n")
                continue

            if user_input.lower() == "help":
                console.print(Panel(
                    "Commands:\n"
                    "  quit, exit, q  - Exit the chat\n"
                    "  clear          - Clear conversation history\n"
                    "  help           - Show this help\n"
                    "  tasks          - List available tasks\n"
                    "\nOr just type a message to chat with the agent.",
                    title="Chat Help"
                ))
                continue

            if user_input.lower() == "tasks":
                _show_tasks_summary(agent.task_registry)
                continue

            # Run the agent with the user's input
            console.print()
            result = await agent.run(user_input, verbose=verbose)
            console.print(f"\n[bold green]Agent:[/bold green] {result}\n")

        except KeyboardInterrupt:
            console.print("\n[dim]Use 'quit' to exit.[/dim]")
            continue
        except EOFError:
            console.print("\n[dim]Goodbye![/dim]")
            break


def _show_tasks_summary(registry) -> None:
    """Show a compact summary of available tasks."""
    table = Table(title="Available Tasks", show_lines=False)
    table.add_column("Task", style="cyan", no_wrap=True)
    table.add_column("Description", style="white")

    for task in sorted(registry.list_tasks(), key=lambda t: t.name):
        desc = task.description
        if len(desc) > 60:
            desc = desc[:57] + "..."
        table.add_row(task.name, desc)

    console.print(table)
    console.print()


def cmd_chat(args: argparse.Namespace) -> None:
    """Start an interactive chat session with the agent."""
    registry = create_default_registry()
    agent = Agent(registry)

    console.print(Panel(
        f"[bold]MacBot Chat[/bold] v{__version__}\n\n"
        f"Provider: {settings.llm_provider.value}\n"
        f"Tasks available: {len(registry)}",
        title="Welcome"
    ))

    asyncio.run(interactive_loop(agent, verbose=args.verbose))


def cmd_run(args: argparse.Namespace) -> None:
    """Run a goal, optionally continuing to interactive mode."""
    # Handle --list-jobs flag
    if getattr(args, "list_jobs", False):
        jobs = load_jobs_from_file()
        if not jobs:
            console.print("[yellow]No jobs found in ~/.macbot/jobs.yaml[/yellow]")
        else:
            console.print(f"[bold]Available jobs[/bold] ({len(jobs)}):\n")
            for name in sorted(jobs.keys()):
                # Show original case from file
                goal_preview = jobs[name].strip().split("\n")[0][:60]
                console.print(f"  [cyan]{name.title()}[/cyan]")
                console.print(f"    {goal_preview}...")
        return

    # Require goal if not listing jobs
    if not args.goal:
        console.print("[red]Error:[/red] goal is required (or use --list-jobs)")
        sys.exit(1)

    # Enable debug logging if --debug flag is set
    if getattr(args, "debug", False):
        setup_logging(verbose=True)
        console.print("[dim]Debug mode enabled[/dim]\n")

    # Check if the goal matches a job name from jobs.yaml
    goal = args.goal
    job_goal = find_job_goal(goal)
    if job_goal:
        console.print(f"[dim]Running job:[/dim] [bold]{goal}[/bold]\n")
        goal = job_goal

    registry = create_default_registry()
    agent = Agent(registry)

    async def _run() -> None:
        # Execute the initial goal
        stream = not getattr(args, "no_stream", False)
        verbose = args.verbose or getattr(args, "debug", False)

        if verbose and not stream:
            console.print(Panel(f"[bold]Goal:[/bold] {goal}", title="Running"))

        result = await agent.run(goal, verbose=verbose, stream=stream)

        # When streaming, text was already printed via stream callback
        # Otherwise, print the final result
        if not stream:
            console.print(f"\n[bold green]Agent:[/bold green] {result}")

        # Continue to interactive mode if requested
        if args.continue_chat:
            await interactive_loop(agent, verbose=verbose)

    asyncio.run(_run())


def cmd_task(args: argparse.Namespace) -> None:
    """Execute a single task directly without LLM involvement."""
    registry = create_default_registry()
    agent = Agent(registry)

    async def _run() -> None:
        # Parse task arguments from command line
        kwargs = {}
        if args.args:
            for arg in args.args:
                if "=" in arg:
                    key, value = arg.split("=", 1)
                    # Try to parse as boolean or number
                    if value.lower() == "true":
                        kwargs[key] = True
                    elif value.lower() == "false":
                        kwargs[key] = False
                    else:
                        try:
                            kwargs[key] = int(value)
                        except ValueError:
                            try:
                                kwargs[key] = float(value)
                            except ValueError:
                                kwargs[key] = value

        if args.verbose:
            console.print(f"[yellow]Executing:[/yellow] {args.task_name}({kwargs})")

        result = await agent.run_single_task(args.task_name, verbose=args.verbose, **kwargs)

        if result.success:
            console.print(f"\n[bold green]Result:[/bold green]\n{result.output}")
        else:
            console.print(f"\n[bold red]Error:[/bold red] {result.error}")
            sys.exit(1)

    asyncio.run(_run())


def cmd_tasks(args: argparse.Namespace) -> None:
    """List all available tasks the agent can execute."""
    registry = create_default_registry()

    if args.verbose:
        # Detailed view with parameters
        table = Table(title="Available Tasks (Detailed)")
        table.add_column("Task Name", style="cyan")
        table.add_column("Description", style="white")
        table.add_column("Parameters", style="yellow")

        for task in sorted(registry.list_tasks(), key=lambda t: t.name):
            params = ", ".join(
                f"{p.name}: {p.type}" + ("" if p.required else "?")
                for p in task.get_parameters()
            )
            table.add_row(task.name, task.description, params or "-")

        console.print(table)
    else:
        # Compact view grouped by category
        tasks_by_category = {
            "Mail": [],
            "Calendar": [],
            "Reminders": [],
            "Notes": [],
            "Safari": [],
            "System": [],
        }

        for task in registry.list_tasks():
            name = task.name
            if "email" in name or "mail" in name:
                tasks_by_category["Mail"].append(task)
            elif "calendar" in name or "event" in name:
                tasks_by_category["Calendar"].append(task)
            elif "reminder" in name:
                tasks_by_category["Reminders"].append(task)
            elif "note" in name:
                tasks_by_category["Notes"].append(task)
            elif "safari" in name or "url" in name or "link" in name or "tab" in name:
                tasks_by_category["Safari"].append(task)
            else:
                tasks_by_category["System"].append(task)

        console.print(f"\n[bold]Available Tasks[/bold] ({len(registry)} total)\n")

        for category, tasks in tasks_by_category.items():
            if tasks:
                task_names = ", ".join(t.name for t in sorted(tasks, key=lambda t: t.name))
                console.print(f"[cyan]{category}:[/cyan] {task_names}")

        console.print("\n[dim]Use 'macbot tasks -v' for detailed view with parameters.[/dim]")


def _get_scheduler_pid() -> int | None:
    """Get the PID of a running background scheduler, or None if not running."""
    if not PID_FILE.exists():
        return None
    try:
        pid = int(PID_FILE.read_text().strip())
        # Check if process is actually running
        os.kill(pid, 0)
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        # PID file exists but process is dead - clean up
        PID_FILE.unlink(missing_ok=True)
        return None


def _daemonize() -> None:
    """Fork the process to run in the background (Unix double-fork)."""
    # First fork
    pid = os.fork()
    if pid > 0:
        # Parent exits
        sys.exit(0)

    # Decouple from parent environment
    os.chdir("/")
    os.setsid()
    os.umask(0)

    # Second fork
    pid = os.fork()
    if pid > 0:
        sys.exit(0)

    # Redirect standard file descriptors
    sys.stdout.flush()
    sys.stderr.flush()

    # Redirect stdin/stdout/stderr to log file
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


def cmd_schedule(args: argparse.Namespace) -> None:
    """Run a goal or task on a repeating schedule."""
    if not args.goal and not args.task:
        console.print("[red]Error:[/red] Specify --goal or --task")
        sys.exit(1)

    # Check if already running in background
    existing_pid = _get_scheduler_pid()
    if existing_pid and args.background:
        console.print(f"[yellow]Scheduler already running[/yellow] (PID {existing_pid})")
        console.print(f"Stop it first with: macbot schedule stop")
        sys.exit(1)

    # Background mode
    if args.background:
        console.print(f"[green]Starting scheduler in background...[/green]")
        if args.goal:
            console.print(f"  Goal: \"{args.goal}\"")
        else:
            console.print(f"  Task: {args.task}")
        console.print(f"  Interval: {args.interval}s")
        console.print(f"  Log: {LOG_FILE}")
        console.print(f"\nUse 'macbot schedule status' to check status")
        console.print(f"Use 'macbot schedule stop' to stop")

        # Store job config before forking (for the child process)
        job_goal = args.goal
        job_task = args.task
        job_interval = args.interval

        _daemonize()

        # Now we're in the daemon process
        print(f"\n{'='*60}")
        print(f"MacBot Scheduler started at {datetime.now().isoformat()}")
        print(f"PID: {os.getpid()}")
        print(f"{'='*60}\n")

        # Set up signal handler for clean shutdown
        def handle_signal(signum, frame):
            print(f"\nReceived signal {signum}, shutting down...")
            PID_FILE.unlink(missing_ok=True)
            sys.exit(0)

        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)

        # Create scheduler in daemon process
        registry = create_default_registry()
        scheduler = TaskScheduler(registry)

        if job_goal:
            scheduler.add_job(
                ScheduledJob(
                    name="scheduled_goal",
                    goal=job_goal,
                    interval_seconds=job_interval,
                )
            )
            print(f"Scheduled goal: \"{job_goal}\" every {job_interval}s")
        else:
            scheduler.add_job(
                ScheduledJob(
                    name="scheduled_task",
                    task_name=job_task,
                    interval_seconds=job_interval,
                )
            )
            print(f"Scheduled task: {job_task} every {job_interval}s")

        try:
            asyncio.run(scheduler.run_forever())
        finally:
            PID_FILE.unlink(missing_ok=True)

    else:
        # Foreground mode
        registry = create_default_registry()
        scheduler = TaskScheduler(registry)

        if args.goal:
            scheduler.add_job(
                ScheduledJob(
                    name="scheduled_goal",
                    goal=args.goal,
                    interval_seconds=args.interval,
                )
            )
            console.print(f"[green]Scheduled goal[/green] to run every {args.interval}s:")
            console.print(f"  \"{args.goal}\"")
        else:
            scheduler.add_job(
                ScheduledJob(
                    name="scheduled_task",
                    task_name=args.task,
                    interval_seconds=args.interval,
                )
            )
            console.print(f"[green]Scheduled task[/green] '{args.task}' to run every {args.interval}s")

        console.print("\n[dim]Press Ctrl+C to stop.[/dim]\n")

        try:
            asyncio.run(scheduler.run_forever())
        except KeyboardInterrupt:
            console.print("\n[dim]Scheduler stopped.[/dim]")


def cmd_schedule_status(args: argparse.Namespace) -> None:
    """Check the status of the background scheduler."""
    pid = _get_scheduler_pid()

    if pid:
        console.print(f"[green]Scheduler is running[/green] (PID {pid})")
        console.print(f"  Log file: {LOG_FILE}")

        # Show last few log lines
        if LOG_FILE.exists():
            console.print(f"\n[dim]Recent log entries:[/dim]")
            lines = LOG_FILE.read_text().strip().split("\n")
            for line in lines[-10:]:
                console.print(f"  {line}")
    else:
        console.print("[yellow]Scheduler is not running[/yellow]")


def cmd_schedule_stop(args: argparse.Namespace) -> None:
    """Stop the background scheduler."""
    pid = _get_scheduler_pid()

    if not pid:
        console.print("[yellow]Scheduler is not running[/yellow]")
        return

    try:
        os.kill(pid, signal.SIGTERM)
        console.print(f"[green]Sent stop signal to scheduler[/green] (PID {pid})")

        # Wait briefly for it to stop
        import time
        for _ in range(10):
            time.sleep(0.2)
            if not _get_scheduler_pid():
                console.print("[green]Scheduler stopped[/green]")
                return

        console.print("[yellow]Scheduler may still be shutting down...[/yellow]")
    except ProcessLookupError:
        console.print("[yellow]Scheduler process not found[/yellow]")
        PID_FILE.unlink(missing_ok=True)
    except PermissionError:
        console.print(f"[red]Permission denied[/red] to stop PID {pid}")


def cmd_schedule_log(args: argparse.Namespace) -> None:
    """Show the scheduler log file."""
    if not LOG_FILE.exists():
        console.print("[yellow]No log file found[/yellow]")
        return

    if args.follow:
        # Tail -f style following
        console.print(f"[dim]Following {LOG_FILE} (Ctrl+C to stop)...[/dim]\n")
        import subprocess
        try:
            subprocess.run(["tail", "-f", str(LOG_FILE)])
        except KeyboardInterrupt:
            pass
    else:
        # Show last N lines
        lines = LOG_FILE.read_text().strip().split("\n")
        for line in lines[-args.lines:]:
            console.print(line)


def cmd_version(args: argparse.Namespace) -> None:
    """Show version and configuration information."""
    console.print(f"[bold]MacBot[/bold] v{__version__}")
    console.print(f"LLM Provider: {settings.llm_provider.value}")
    console.print(f"Max iterations: {settings.max_iterations}")

    registry = create_default_registry()
    console.print(f"Tasks available: {len(registry)}")


# Unified service commands
def cmd_start(args: argparse.Namespace) -> None:
    """Start the macbot service (cron + telegram)."""
    from macbot.service import run_service
    run_service(daemon=args.daemon, verbose=args.verbose)


def cmd_stop(args: argparse.Namespace) -> None:
    """Stop the macbot service."""
    from macbot.service import get_service_pid, stop_service

    pid = get_service_pid()
    if not pid:
        console.print("[yellow]Service is not running[/yellow]")
        return

    console.print(f"Stopping service (PID {pid})...")
    if stop_service():
        console.print("[green]Service stopped[/green]")
    else:
        console.print("[yellow]Service may still be shutting down[/yellow]")


def cmd_status(args: argparse.Namespace) -> None:
    """Show macbot service status."""
    from macbot.service import LOG_FILE, MacbotService, get_service_pid

    pid = get_service_pid()

    # Service running status
    if pid:
        console.print(f"[green]Service is running[/green] (PID {pid})")
    else:
        console.print("[yellow]Service is not running[/yellow]")

    # Get configuration status
    service = MacbotService()
    status = service.get_status()

    console.print(f"\n[bold]Cron Jobs[/bold]")
    if status["cron"]["jobs_total"] > 0:
        console.print(f"  Jobs: {status['cron']['jobs_enabled']} enabled / {status['cron']['jobs_total']} total")
    else:
        console.print(f"  [dim]No jobs configured[/dim]")
        console.print(f"  [dim]→ Use 'macbot cron import <file>' to add jobs[/dim]")

    console.print(f"\n[bold]Telegram[/bold]")
    if status["telegram"]["enabled"]:
        chat_id = status["telegram"].get("chat_id")
        if chat_id:
            console.print(f"  Chat ID: {chat_id}")
        else:
            console.print(f"  [yellow]Chat ID not set[/yellow]")
            console.print(f"  [dim]→ Run 'macbot telegram whoami' to get your chat ID[/dim]")
    else:
        console.print(f"  [dim]Not configured[/dim]")
        console.print(f"  [dim]→ Set MACBOT_TELEGRAM_BOT_TOKEN to enable[/dim]")

    # Show recent log if running
    if pid and LOG_FILE.exists():
        console.print(f"\n[bold]Recent Log[/bold]")
        lines = LOG_FILE.read_text().strip().split("\n")
        for line in lines[-5:]:
            console.print(f"  [dim]{line}[/dim]")


def cmd_onboard(args: argparse.Namespace) -> None:
    """Interactive setup wizard for new users."""
    import platform
    import shutil
    import subprocess

    console.print(f"\n[bold]Welcome to MacBot![/bold] v{__version__}")
    console.print("Let's get you set up.\n")

    env_file = MACBOT_DIR / ".env"
    env_vars: dict[str, str] = {}

    def step_header(num: int, total: int, title: str) -> None:
        console.print(f"\n[bold cyan]Step {num}/{total}: {title}[/bold cyan]")
        console.print("─" * 40)

    def prompt_choice(question: str, options: list[str], default: int = 1) -> int:
        """Prompt user to choose from options."""
        console.print(f"\n{question}")
        for i, opt in enumerate(options, 1):
            marker = "[bold green]>[/bold green]" if i == default else " "
            console.print(f"  {marker} [{i}] {opt}")
        while True:
            response = console.input(f"\nChoice [{default}]: ").strip()
            if not response:
                return default
            try:
                choice = int(response)
                if 1 <= choice <= len(options):
                    return choice
            except ValueError:
                pass
            console.print("[red]Invalid choice[/red]")

    def prompt_yes_no(question: str, default: bool = True) -> bool:
        """Prompt for yes/no."""
        hint = "[Y/n]" if default else "[y/N]"
        response = console.input(f"{question} {hint}: ").strip().lower()
        if not response:
            return default
        return response in ("y", "yes")

    def prompt_secret(question: str) -> str:
        """Prompt for a secret value (like API key)."""
        import getpass
        return getpass.getpass(f"{question}: ")

    def open_system_settings(pane: str) -> None:
        """Open System Settings to a specific pane."""
        # macOS Ventura+ uses different URL scheme
        subprocess.run(
            ["open", f"x-apple.systempreferences:com.apple.preference.security?{pane}"],
            capture_output=True,
        )

    def test_applescript_access(app: str, script: str) -> bool:
        """Test if we have AppleScript access to an app."""
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                timeout=10,
            )
            return result.returncode == 0
        except Exception:
            return False

    total_steps = 5

    # =========================================================================
    # Step 1: LLM Provider
    # =========================================================================
    step_header(1, total_steps, "LLM Provider")

    # Check if already configured
    has_anthropic = bool(settings.anthropic_api_key)
    has_openai = bool(settings.openai_api_key)

    if has_anthropic or has_openai:
        current = "Anthropic" if settings.llm_provider.value == "anthropic" else "OpenAI"
        console.print(f"[green]✓[/green] Already configured: {current}")
        if not prompt_yes_no("Reconfigure?", default=False):
            pass  # Keep existing config
        else:
            has_anthropic = False
            has_openai = False

    if not has_anthropic and not has_openai:
        choice = prompt_choice(
            "Which LLM provider would you like to use?",
            ["Anthropic (Claude) - Recommended", "OpenAI (GPT-4)"],
            default=1,
        )

        if choice == 1:
            console.print("\nGet your API key from: [link]https://console.anthropic.com/[/link]")
            api_key = prompt_secret("Enter your Anthropic API key")
            if api_key:
                env_vars["MACBOT_LLM_PROVIDER"] = "anthropic"
                env_vars["MACBOT_ANTHROPIC_API_KEY"] = api_key

                # Validate the key
                console.print("Validating API key...", end=" ")
                try:
                    from anthropic import Anthropic
                    client = Anthropic(api_key=api_key)
                    # Simple validation - just check if we can create a client
                    console.print("[green]✓ Valid[/green]")
                except Exception as e:
                    console.print(f"[yellow]Warning: {e}[/yellow]")
        else:
            console.print("\nGet your API key from: [link]https://platform.openai.com/api-keys[/link]")
            api_key = prompt_secret("Enter your OpenAI API key")
            if api_key:
                env_vars["MACBOT_LLM_PROVIDER"] = "openai"
                env_vars["MACBOT_OPENAI_API_KEY"] = api_key
                console.print("[green]✓ API key saved[/green]")

    # =========================================================================
    # Step 2: macOS Permissions
    # =========================================================================
    step_header(2, total_steps, "macOS Permissions")

    if platform.system() != "Darwin":
        console.print("[yellow]Skipping - not on macOS[/yellow]")
    else:
        console.print("MacBot needs permission to control apps via AppleScript.")
        console.print("We'll open System Settings for you to grant access.\n")

        apps_to_test = [
            ("Mail", 'tell application "Mail" to count of accounts'),
            ("Calendar", 'tell application "Calendar" to count of calendars'),
            ("Reminders", 'tell application "Reminders" to count of lists'),
            ("Notes", 'tell application "Notes" to count of notes'),
            ("Safari", 'tell application "Safari" to count of windows'),
        ]

        # Check current permissions
        missing_perms = []
        for app_name, script in apps_to_test:
            if not test_applescript_access(app_name, script):
                missing_perms.append(app_name)

        if not missing_perms:
            console.print("[green]✓[/green] All app permissions already granted!")
        else:
            console.print(f"Missing permissions for: {', '.join(missing_perms)}")
            console.print("\nOpening System Settings > Privacy & Security > Automation...")
            open_system_settings("Privacy_Automation")

            console.print("\n[bold]Grant Terminal (or your terminal app) access to:[/bold]")
            for app in missing_perms:
                console.print(f"  • {app}")

            console.input("\nPress [bold]Enter[/bold] when done...")

            # Re-check
            still_missing = []
            for app_name, script in apps_to_test:
                if not test_applescript_access(app_name, script):
                    still_missing.append(app_name)

            if not still_missing:
                console.print("[green]✓[/green] All permissions granted!")
            else:
                console.print(f"[yellow]![/yellow] Still missing: {', '.join(still_missing)}")
                console.print("    You can grant these later and run 'macbot doctor' to verify.")

    # =========================================================================
    # Step 3: Browser Automation (Optional)
    # =========================================================================
    step_header(3, total_steps, "Browser Automation (Optional)")

    console.print("For advanced browser automation, MacBot can use physical clicks.")
    console.print("This requires 'cliclick' and Accessibility permissions.\n")

    if not prompt_yes_no("Set up browser automation?", default=True):
        console.print("[dim]Skipped[/dim]")
    else:
        # Check for cliclick
        cliclick_path = shutil.which("cliclick")
        if cliclick_path:
            console.print(f"[green]✓[/green] cliclick already installed: {cliclick_path}")
        else:
            # Check for Homebrew
            brew_path = shutil.which("brew")
            if brew_path:
                if prompt_yes_no("Install cliclick via Homebrew?", default=True):
                    console.print("Installing cliclick...")
                    result = subprocess.run(
                        ["brew", "install", "cliclick"],
                        capture_output=True,
                        text=True,
                    )
                    if result.returncode == 0:
                        console.print("[green]✓[/green] cliclick installed")
                    else:
                        console.print(f"[red]✗[/red] Installation failed: {result.stderr[:100]}")
            else:
                console.print("[yellow]![/yellow] Homebrew not found")
                console.print("    Install manually: https://github.com/BlueM/cliclick")

        # Check Accessibility permissions
        cliclick_path = shutil.which("cliclick")
        if cliclick_path:
            console.print("\nTesting Accessibility permissions...")
            try:
                result = subprocess.run(
                    ["cliclick", "p:."],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    console.print("[green]✓[/green] Accessibility permissions OK")
                else:
                    console.print("[yellow]![/yellow] Accessibility permission needed")
                    console.print("\nOpening System Settings > Privacy & Security > Accessibility...")
                    open_system_settings("Privacy_Accessibility")
                    console.print("\n[bold]Grant access to Terminal (or your terminal app)[/bold]")
                    console.input("\nPress [bold]Enter[/bold] when done...")
            except Exception as e:
                console.print(f"[yellow]![/yellow] Could not test: {e}")

        # Check Safari JavaScript
        console.print("\nFor Safari automation, enable JavaScript from Apple Events:")
        console.print("  Safari > Settings > Advanced > 'Allow JavaScript from Apple Events'")
        console.input("\nPress [bold]Enter[/bold] when done...")

    # =========================================================================
    # Step 4: Telegram (Optional)
    # =========================================================================
    step_header(4, total_steps, "Telegram Integration (Optional)")

    console.print("Receive tasks and get results via Telegram.\n")

    has_telegram = bool(settings.telegram_bot_token)
    if has_telegram:
        console.print("[green]✓[/green] Telegram already configured")
        if not prompt_yes_no("Reconfigure?", default=False):
            pass
        else:
            has_telegram = False

    if not has_telegram:
        if not prompt_yes_no("Set up Telegram?", default=False):
            console.print("[dim]Skipped[/dim]")
        else:
            console.print("\n[bold]To create a Telegram bot:[/bold]")
            console.print("  1. Open Telegram and message @BotFather")
            console.print("  2. Send /newbot and follow the prompts")
            console.print("  3. Copy the bot token\n")

            token = prompt_secret("Enter your bot token")
            if token:
                # Validate token
                console.print("Validating token...", end=" ")
                try:
                    async def _validate():
                        from macbot.telegram.bot import validate_token
                        return await validate_token(token)
                    ok, msg = asyncio.run(_validate())
                    if ok:
                        console.print(f"[green]✓ Connected as {msg}[/green]")
                        env_vars["MACBOT_TELEGRAM_BOT_TOKEN"] = token

                        # Get chat ID
                        console.print("\n[bold]Now let's get your chat ID:[/bold]")
                        console.print("  Send any message to your new bot in Telegram...")

                        async def _get_chat_id():
                            from macbot.telegram import TelegramBot
                            bot = TelegramBot(token)
                            offset = None
                            for _ in range(30):  # Wait up to 30 seconds
                                updates = await bot.get_updates(offset=offset, timeout=1)
                                for update in updates:
                                    offset = update.update_id + 1
                                    if update.message:
                                        await bot.close()
                                        return str(update.message.chat_id)
                            await bot.close()
                            return None

                        console.print("[dim]Waiting for message...[/dim]")
                        chat_id = asyncio.run(_get_chat_id())
                        if chat_id:
                            console.print(f"[green]✓[/green] Your chat ID: {chat_id}")
                            env_vars["MACBOT_TELEGRAM_CHAT_ID"] = chat_id
                        else:
                            console.print("[yellow]![/yellow] Timeout - no message received")
                            console.print("    Run 'macbot telegram whoami' later to get your chat ID")
                    else:
                        console.print(f"[red]✗ Invalid: {msg}[/red]")
                except Exception as e:
                    console.print(f"[red]✗ Error: {e}[/red]")

    # =========================================================================
    # Step 5: Save & Test
    # =========================================================================
    step_header(5, total_steps, "Save & Test")

    # Save environment variables
    if env_vars:
        console.print("Saving configuration...")
        MACBOT_DIR.mkdir(parents=True, exist_ok=True)

        # Read existing env file if present
        existing_env = {}
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    existing_env[key.strip()] = value.strip()

        # Merge with new values
        existing_env.update(env_vars)

        # Write back
        with open(env_file, "w") as f:
            f.write("# MacBot Configuration\n")
            f.write("# Generated by 'macbot onboard'\n\n")
            for key, value in sorted(existing_env.items()):
                f.write(f"{key}={value}\n")

        console.print(f"[green]✓[/green] Saved to {env_file}")
        console.print("\n[yellow]Note:[/yellow] To use the new configuration, either:")
        console.print(f"  • Run: [bold]source {env_file}[/bold]")
        console.print(f"  • Or add to your shell profile: [bold]source {env_file}[/bold]")

        # Source the env file for this session
        for key, value in env_vars.items():
            os.environ[key] = value

    # Run a test
    console.print("\n[bold]Running a quick test...[/bold]")

    try:
        # Reload settings with new env vars
        from macbot.config import Settings
        test_settings = Settings()

        if test_settings.anthropic_api_key or test_settings.openai_api_key:
            registry = create_default_registry()
            agent = Agent(registry, config=test_settings)

            async def _test():
                return await agent.run("What time is it?", stream=False)

            result = asyncio.run(_test())
            console.print(f"[green]✓[/green] Test successful!")
            console.print(f"  Response: {result[:100]}{'...' if len(result) > 100 else ''}")
        else:
            console.print("[yellow]![/yellow] No API key configured - skipping test")
    except Exception as e:
        console.print(f"[red]✗[/red] Test failed: {e}")
        console.print("    Run 'macbot doctor' to diagnose issues")

    # Final summary
    console.print("\n" + "═" * 40)
    console.print("[bold green]Setup complete![/bold green]")
    console.print("═" * 40)

    console.print("\n[bold]Quick start:[/bold]")
    console.print("  macbot run \"Check my emails\"     # Run a goal")
    console.print("  macbot doctor                    # Verify setup")
    console.print("  macbot status                    # Check service status")

    if "MACBOT_TELEGRAM_BOT_TOKEN" in env_vars:
        console.print("  macbot start -d                  # Start service (with Telegram)")

    console.print("\n[dim]Run 'macbot --help' for more commands.[/dim]\n")


def cmd_doctor(args: argparse.Namespace) -> None:
    """Check system prerequisites and configuration."""
    import platform
    import shutil

    console.print(f"\n[bold]MacBot Doctor[/bold] v{__version__}\n")

    all_ok = True

    def check(name: str, ok: bool, message: str, hint: str | None = None) -> bool:
        nonlocal all_ok
        if ok:
            console.print(f"  [green]✓[/green] {name}: {message}")
        else:
            console.print(f"  [red]✗[/red] {name}: {message}")
            if hint:
                console.print(f"    [dim]→ {hint}[/dim]")
            all_ok = False
        return ok

    def warn(name: str, message: str, hint: str | None = None) -> None:
        console.print(f"  [yellow]![/yellow] {name}: {message}")
        if hint:
            console.print(f"    [dim]→ {hint}[/dim]")

    # System checks
    console.print("[bold]System[/bold]")

    # Python version
    py_version = platform.python_version()
    py_ok = tuple(map(int, py_version.split(".")[:2])) >= (3, 10)
    check("Python", py_ok, py_version, "Requires Python 3.10+")

    # Platform
    system = platform.system()
    if system == "Darwin":
        check("Platform", True, f"macOS ({platform.mac_ver()[0]})")
    else:
        warn("Platform", f"{system} (macOS recommended)",
             "macOS automation tasks require macOS")

    # Configuration checks
    console.print("\n[bold]Configuration[/bold]")

    # LLM Provider
    provider = settings.llm_provider.value
    check("LLM Provider", True, provider)

    # API Key
    if settings.llm_provider.value == "anthropic":
        api_key = settings.anthropic_api_key
        key_name = "MACBOT_ANTHROPIC_API_KEY"
        model = settings.anthropic_model
    else:
        api_key = settings.openai_api_key
        key_name = "MACBOT_OPENAI_API_KEY"
        model = settings.openai_model

    if api_key:
        masked = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else "***"
        check("API Key", True, f"{masked}")
    else:
        check("API Key", False, "Not set",
              f"Set {key_name} in environment or .env file")

    check("Model", True, model)

    # Data directory
    data_dir = Path.home() / ".macbot"
    if data_dir.exists():
        check("Data Directory", True, str(data_dir))
    else:
        warn("Data Directory", f"{data_dir} (will be created on first use)")

    # macOS Automation Scripts
    console.print("\n[bold]macOS Automation[/bold]")

    # Find scripts directory
    script_locations = [
        Path(__file__).parent.parent.parent.parent / "macos-automation",
        Path.cwd() / "macos-automation",
        Path.home() / "macos-automation",
    ]

    scripts_dir = None
    for loc in script_locations:
        if loc.exists() and (loc / "mail").exists():
            scripts_dir = loc
            break

    if scripts_dir:
        check("Scripts Directory", True, str(scripts_dir))

        # Check key scripts exist
        key_scripts = [
            "mail/get-unread-summary.sh",
            "calendar/get-today-events.sh",
            "reminders/get-due-today.sh",
            "notes/list-notes.sh",
            "safari/get-current-page.sh",
        ]

        missing = []
        for script in key_scripts:
            script_path = scripts_dir / script
            if not script_path.exists():
                missing.append(script)
            elif not os.access(script_path, os.X_OK):
                missing.append(f"{script} (not executable)")

        if not missing:
            check("Scripts", True, f"{len(key_scripts)} key scripts found")
        else:
            check("Scripts", False, f"Missing: {', '.join(missing)}",
                  "Run: chmod +x macos-automation/**/*.sh")
    else:
        check("Scripts Directory", False, "Not found",
              "Clone macos-automation to project directory")

    # osascript (AppleScript)
    osascript = shutil.which("osascript")
    if osascript:
        check("osascript", True, osascript)
    else:
        check("osascript", False, "Not found",
              "osascript is required for macOS automation (macOS only)")

    # Test AppleScript access to apps
    console.print("\n[bold]App Access Tests[/bold]")

    def test_app_access(app_name: str, test_script: str) -> tuple[bool, str]:
        """Test if we can access an app via AppleScript."""
        import subprocess
        try:
            result = subprocess.run(
                ["osascript", "-e", test_script],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return True, result.stdout.strip()[:50] or "OK"
            else:
                error = result.stderr.strip()
                # Parse common error codes
                if "-1743" in error:
                    return False, "Permission denied (grant in System Settings > Privacy > Automation)"
                elif "-2741" in error:
                    return False, "AppleScript syntax error (special chars in data?)"
                elif "-1728" in error:
                    return False, f"{app_name} not found or not responding"
                else:
                    return False, error[:80]
        except subprocess.TimeoutExpired:
            return False, "Timeout (app not responding)"
        except Exception as e:
            return False, str(e)[:80]

    # Test Notes
    ok, msg = test_app_access("Notes", 'tell application "Notes" to count of notes')
    check("Notes.app", ok, msg,
          "Grant access in System Settings > Privacy & Security > Automation" if not ok else None)

    # Test Mail
    ok, msg = test_app_access("Mail", 'tell application "Mail" to count of accounts')
    check("Mail.app", ok, msg,
          "Grant access in System Settings > Privacy & Security > Automation" if not ok else None)

    # Test Calendar
    ok, msg = test_app_access("Calendar", 'tell application "Calendar" to count of calendars')
    check("Calendar.app", ok, msg,
          "Grant access in System Settings > Privacy & Security > Automation" if not ok else None)

    # Test Reminders
    ok, msg = test_app_access("Reminders", 'tell application "Reminders" to count of lists')
    check("Reminders.app", ok, msg,
          "Grant access in System Settings > Privacy & Security > Automation" if not ok else None)

    # Test Safari
    ok, msg = test_app_access("Safari", 'tell application "Safari" to count of windows')
    check("Safari.app", ok, msg,
          "Grant access in System Settings > Privacy & Security > Automation" if not ok else None)

    # Browser Automation Tools
    console.print("\n[bold]Browser Automation[/bold]")

    # Check for cliclick (used for physical mouse clicks)
    cliclick_path = shutil.which("cliclick")
    if cliclick_path:
        # Test if cliclick has Accessibility permissions
        import subprocess
        try:
            result = subprocess.run(
                ["cliclick", "p:."],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                check("cliclick", True, f"{cliclick_path} (Accessibility OK)")
            else:
                error = result.stderr.strip()
                if "Accessibility" in error or "permission" in error.lower():
                    check("cliclick", False, "Accessibility permission denied",
                          "Grant Terminal Accessibility in System Settings > Privacy & Security > Accessibility")
                else:
                    check("cliclick", False, error[:60])
        except subprocess.TimeoutExpired:
            check("cliclick", False, "Timeout testing cliclick")
        except Exception as e:
            check("cliclick", False, str(e)[:60])
    else:
        warn("cliclick", "Not installed (optional, for physical clicks)",
             "Install with: brew install cliclick")

    # Check for JavaScript execution capability in Safari
    js_test = 'tell application "Safari" to do JavaScript "1+1" in current tab of front window'
    try:
        result = subprocess.run(
            ["osascript", "-e", js_test],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            check("Safari JavaScript", True, "Allowed")
        else:
            error = result.stderr.strip()
            if "-1743" in error:
                check("Safari JavaScript", False, "Permission denied",
                      "Enable: Safari > Settings > Advanced > 'Allow JavaScript from Apple Events'")
            elif "window" in error.lower() or "tab" in error.lower():
                warn("Safari JavaScript", "No Safari window open (can't test)")
            else:
                warn("Safari JavaScript", f"Could not test: {error[:40]}")
    except Exception as e:
        warn("Safari JavaScript", f"Could not test: {str(e)[:40]}")

    # Tasks
    console.print("\n[bold]Tasks[/bold]")

    registry = create_default_registry()
    task_count = len(registry)
    check("Registered Tasks", task_count > 0, f"{task_count} tasks")

    # Categorize tasks
    macos_tasks = [t for t in registry.list_tasks() if any(
        x in t.name for x in ["email", "mail", "calendar", "event", "reminder", "note", "safari", "url", "tab", "link"]
    )]
    system_tasks = [t for t in registry.list_tasks() if t not in macos_tasks]

    console.print(f"    [dim]System tasks: {len(system_tasks)}[/dim]")
    console.print(f"    [dim]macOS tasks: {len(macos_tasks)}[/dim]")

    # Telegram Integration
    console.print("\n[bold]Telegram Integration[/bold]")

    if settings.telegram_bot_token:
        # Token format check
        if ":" not in settings.telegram_bot_token:
            check("Token Format", False, "Invalid format (expected ID:SECRET)")
        else:
            masked = settings.telegram_bot_token[:8] + "..." + settings.telegram_bot_token[-4:]
            check("Token", True, masked)

            # Test API connection
            async def _test_telegram() -> tuple[bool, str]:
                from macbot.telegram.bot import validate_token
                return await validate_token(settings.telegram_bot_token)

            try:
                ok, msg = asyncio.run(_test_telegram())
                if ok:
                    check("API Connection", True, f"Connected as {msg}")
                else:
                    check("API Connection", False, msg)
            except Exception as e:
                check("API Connection", False, str(e)[:50])

        # Chat ID check
        if settings.telegram_chat_id:
            check("Chat ID", True, settings.telegram_chat_id)
        else:
            warn("Chat ID", "Not configured",
                 "Run 'macbot telegram whoami' to get your chat ID")

        # Service status
        telegram_pid = _get_telegram_pid()
        if telegram_pid:
            check("Service", True, f"Running (PID {telegram_pid})")
        else:
            warn("Service", "Not running",
                 "Start with 'macbot telegram start'")
    else:
        warn("Telegram", "Not configured",
             "Set MACBOT_TELEGRAM_BOT_TOKEN to enable")

    # Summary
    console.print()
    if all_ok:
        console.print("[green]All checks passed![/green] MacBot is ready to use.\n")
    else:
        console.print("[yellow]Some checks failed.[/yellow] Please fix the issues above.\n")
        sys.exit(1)


# Cron commands
def cmd_cron_add(args: argparse.Namespace) -> None:
    """Add a new scheduled job."""
    service = CronService(storage_path=settings.get_cron_storage_path())

    # Determine schedule type
    if args.at:
        try:
            at_time = datetime.fromisoformat(args.at)
            at_ms = int(at_time.timestamp() * 1000)
            schedule = CronSchedule(kind=ScheduleKind.AT, at_ms=at_ms)
        except ValueError:
            console.print(f"[red]Invalid datetime:[/red] {args.at}")
            console.print("Use ISO format: YYYY-MM-DDTHH:MM:SS")
            sys.exit(1)
    elif args.every:
        schedule = CronSchedule(kind=ScheduleKind.EVERY, every_ms=args.every * 1000)
    elif args.cron:
        schedule = CronSchedule(
            kind=ScheduleKind.CRON,
            cron_expr=args.cron,
            timezone=args.timezone or "UTC",
        )
    else:
        console.print("[red]Error:[/red] Specify --at, --every, or --cron")
        sys.exit(1)

    job = service.create_job(CronJobCreate(
        name=args.name,
        description=args.description,
        schedule=schedule,
        payload=CronPayload(
            message=args.message,
            kind="agent_turn" if args.agent else "system_event",
        ),
        enabled=not args.disabled,
    ))

    console.print(f"[green]Created job:[/green] {job.name}")
    console.print(f"  ID: {job.id}")
    if job.state.next_run_at:
        console.print(f"  Next run: {job.state.next_run_at.isoformat()}")


def cmd_cron_list(args: argparse.Namespace) -> None:
    """List all scheduled jobs."""
    service = CronService(storage_path=settings.get_cron_storage_path())
    jobs = service.list_jobs()

    if not jobs:
        console.print("[yellow]No scheduled jobs.[/yellow]")
        return

    table = Table(title="Scheduled Jobs")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="white")
    table.add_column("Schedule", style="yellow")
    table.add_column("Enabled", style="green")
    table.add_column("Next Run", style="blue")
    table.add_column("Runs", style="magenta")

    for job in jobs:
        if job.schedule.kind == ScheduleKind.AT:
            sched_str = f"at {datetime.fromtimestamp(job.schedule.at_ms / 1000).isoformat()}"
        elif job.schedule.kind == ScheduleKind.EVERY:
            sched_str = f"every {job.schedule.every_ms // 1000}s"
        else:
            sched_str = job.schedule.cron_expr or "?"

        next_run = job.state.next_run_at.isoformat() if job.state.next_run_at else "-"

        table.add_row(
            job.id,
            job.name,
            sched_str,
            "Yes" if job.enabled else "No",
            next_run,
            str(job.state.run_count),
        )

    console.print(table)


def cmd_cron_run(args: argparse.Namespace) -> None:
    """Run a scheduled job immediately."""
    service = CronService(storage_path=settings.get_cron_storage_path())

    job = service.get_job(args.job_id)
    if not job:
        console.print(f"[red]Job not found:[/red] {args.job_id}")
        sys.exit(1)

    async def _run() -> None:
        result = await service.run_job(args.job_id)
        if result and result.success:
            console.print(f"[green]Completed:[/green] {result.output}")
        elif result:
            console.print(f"[red]Failed:[/red] {result.error}")

    console.print(f"Running: {job.name}")
    asyncio.run(_run())


def cmd_cron_remove(args: argparse.Namespace) -> None:
    """Remove a scheduled job."""
    service = CronService(storage_path=settings.get_cron_storage_path())

    job = service.get_job(args.job_id)
    if not job:
        console.print(f"[red]Job not found:[/red] {args.job_id}")
        sys.exit(1)

    if service.delete_job(args.job_id):
        console.print(f"[green]Removed:[/green] {job.name}")
    else:
        console.print(f"[red]Failed to remove:[/red] {args.job_id}")
        sys.exit(1)


def cmd_cron_enable(args: argparse.Namespace) -> None:
    """Enable a scheduled job."""
    service = CronService(storage_path=settings.get_cron_storage_path())

    if service.enable_job(args.job_id):
        console.print(f"[green]Enabled:[/green] {args.job_id}")
    else:
        console.print(f"[red]Job not found:[/red] {args.job_id}")
        sys.exit(1)


def cmd_cron_disable(args: argparse.Namespace) -> None:
    """Disable a scheduled job."""
    service = CronService(storage_path=settings.get_cron_storage_path())

    if service.disable_job(args.job_id):
        console.print(f"[yellow]Disabled:[/yellow] {args.job_id}")
    else:
        console.print(f"[red]Job not found:[/red] {args.job_id}")
        sys.exit(1)


def cmd_cron_import(args: argparse.Namespace) -> None:
    """Import jobs from a YAML configuration file.

    This will:
    1. Stop any running cron scheduler
    2. Clear all existing jobs
    3. Import jobs from the file
    """
    config_path = Path(args.file)

    if not config_path.exists():
        console.print(f"[red]File not found:[/red] {config_path}")
        sys.exit(1)

    # Load and parse YAML file
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        console.print(f"[red]Invalid YAML:[/red] {e}")
        sys.exit(1)

    if not config:
        console.print("[red]Empty configuration file[/red]")
        sys.exit(1)

    jobs_config = config.get("jobs", [])
    if not jobs_config:
        console.print("[yellow]No jobs defined in configuration[/yellow]")
        sys.exit(0)

    # Stop running scheduler if any
    pid = _get_scheduler_pid()
    if pid:
        console.print(f"[yellow]Stopping running scheduler[/yellow] (PID {pid})...")
        try:
            os.kill(pid, signal.SIGTERM)
            import time
            for _ in range(20):
                time.sleep(0.2)
                if not _get_scheduler_pid():
                    break
        except (ProcessLookupError, PermissionError):
            pass
        PID_FILE.unlink(missing_ok=True)

    # Clear existing jobs and import new ones
    service = CronService(storage_path=settings.get_cron_storage_path())

    # Clear all existing jobs
    existing = service.list_jobs()
    if existing:
        console.print(f"[yellow]Removing {len(existing)} existing jobs...[/yellow]")
        for job in existing:
            service.delete_job(job.id)

    # Import new jobs
    console.print(f"\n[bold]Importing {len(jobs_config)} jobs from {config_path.name}[/bold]\n")

    imported_count = 0
    for job_config in jobs_config:
        name = job_config.get("name")
        if not name:
            console.print(f"[red]Skipping job without name[/red]")
            continue

        goal = job_config.get("goal") or job_config.get("message")
        if not goal:
            console.print(f"[red]Skipping '{name}':[/red] no goal/message")
            continue

        # Parse schedule
        interval = job_config.get("interval")
        cron_expr = job_config.get("cron")
        at_time = job_config.get("at")

        if interval:
            schedule = CronSchedule(kind=ScheduleKind.EVERY, every_ms=interval * 1000)
            sched_str = f"every {interval}s"
        elif cron_expr:
            tz = job_config.get("timezone", "UTC")
            schedule = CronSchedule(kind=ScheduleKind.CRON, cron_expr=cron_expr, timezone=tz)
            sched_str = cron_expr
        elif at_time:
            try:
                dt = datetime.fromisoformat(at_time)
                at_ms = int(dt.timestamp() * 1000)
                schedule = CronSchedule(kind=ScheduleKind.AT, at_ms=at_ms)
                sched_str = f"at {at_time}"
            except ValueError:
                console.print(f"[red]Skipping '{name}':[/red] invalid datetime '{at_time}'")
                continue
        else:
            console.print(f"[red]Skipping '{name}':[/red] no schedule (interval, cron, or at)")
            continue

        # Create the job
        job = service.create_job(CronJobCreate(
            name=name,
            description=job_config.get("description"),
            schedule=schedule,
            payload=CronPayload(
                message=goal,
                kind="agent_turn",  # Always use agent for goals
            ),
            enabled=job_config.get("enabled", True),
        ))

        imported_count += 1
        status = "[green]✓[/green]" if job.enabled else "[yellow]○[/yellow]"
        console.print(f"  {status} {name} ({sched_str})")

    console.print(f"\n[green]Imported {imported_count} jobs[/green]")
    console.print(f"Storage: {service.storage_path}")
    console.print(f"\nRun [bold]macbot cron start[/bold] to start the scheduler")


def cmd_cron_start(args: argparse.Namespace) -> None:
    """Start the cron scheduler to run all registered jobs."""
    service = CronService(storage_path=settings.get_cron_storage_path())

    jobs = service.list_jobs()
    enabled_jobs = [j for j in jobs if j.enabled]

    if not jobs:
        console.print("[yellow]No jobs registered.[/yellow]")
        console.print("Use [bold]macbot cron import <file>[/bold] to import jobs")
        sys.exit(0)

    if not enabled_jobs:
        console.print(f"[yellow]No enabled jobs.[/yellow] ({len(jobs)} jobs disabled)")
        sys.exit(0)

    # Check if already running
    existing_pid = _get_scheduler_pid()
    if existing_pid and args.background:
        console.print(f"[yellow]Scheduler already running[/yellow] (PID {existing_pid})")
        console.print("Stop it first with: macbot cron stop")
        sys.exit(1)

    console.print(f"[bold]Starting cron scheduler[/bold] ({len(enabled_jobs)} enabled jobs)")
    console.print()

    # Show jobs that will run
    for job in enabled_jobs:
        if job.schedule.kind == ScheduleKind.EVERY:
            sched_str = f"every {job.schedule.every_ms // 1000}s"
        elif job.schedule.kind == ScheduleKind.CRON:
            sched_str = job.schedule.cron_expr
        else:
            sched_str = f"at {datetime.fromtimestamp(job.schedule.at_ms / 1000).isoformat()}"

        goal_preview = job.payload.message[:50] + "..." if len(job.payload.message) > 50 else job.payload.message
        console.print(f"  [cyan]{job.name}[/cyan] ({sched_str})")
        console.print(f"    {goal_preview}")
    console.print()

    if args.background:
        # Background mode
        console.print(f"[green]Starting in background...[/green]")
        console.print(f"  Log: {LOG_FILE}")
        console.print(f"\nUse 'macbot cron stop' to stop")

        _daemonize()

        # Now in daemon process
        print(f"\n{'='*60}")
        print(f"MacBot Cron Service started at {datetime.now().isoformat()}")
        print(f"PID: {os.getpid()}")
        print(f"Jobs: {len(enabled_jobs)} enabled")
        print(f"{'='*60}\n")

        # Set up signal handler
        def handle_signal(signum, frame):
            print(f"\nReceived signal {signum}, shutting down...")
            PID_FILE.unlink(missing_ok=True)
            sys.exit(0)

        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)

        # Set up agent handler for the cron service
        registry = create_default_registry()
        agent = Agent(registry)

        async def agent_handler(payload: CronPayload):
            from macbot.cron.executor import ExecutionResult
            try:
                result = await agent.run(payload.message)
                return ExecutionResult(success=True, output=result)
            except Exception as e:
                return ExecutionResult(success=False, error=str(e))

        # Create fresh service in daemon
        daemon_service = CronService(storage_path=settings.get_cron_storage_path())
        daemon_service.set_agent_handler(agent_handler)

        try:
            asyncio.run(daemon_service.start())
            # Keep running
            asyncio.run(_cron_run_forever(daemon_service))
        finally:
            PID_FILE.unlink(missing_ok=True)
    else:
        # Foreground mode
        console.print("[dim]Press Ctrl+C to stop.[/dim]\n")

        registry = create_default_registry()
        agent = Agent(registry)

        async def agent_handler(payload: CronPayload):
            from macbot.cron.executor import ExecutionResult
            try:
                print(f"\n[{datetime.now().isoformat()}] Running: {payload.message[:50]}...")
                result = await agent.run(payload.message)
                print(f"Result: {result[:200]}..." if len(result) > 200 else f"Result: {result}")
                return ExecutionResult(success=True, output=result)
            except Exception as e:
                print(f"Error: {e}")
                return ExecutionResult(success=False, error=str(e))

        service.set_agent_handler(agent_handler)

        try:
            asyncio.run(_cron_run_foreground(service))
        except KeyboardInterrupt:
            console.print("\n[dim]Scheduler stopped.[/dim]")


async def _cron_run_forever(service: CronService) -> None:
    """Run the cron service forever (for daemon mode)."""
    await service.start()
    while True:
        await asyncio.sleep(1)


async def _cron_run_foreground(service: CronService) -> None:
    """Run the cron service in foreground."""
    await service.start()
    try:
        while True:
            await asyncio.sleep(1)
    finally:
        await service.stop()


def cmd_cron_stop(args: argparse.Namespace) -> None:
    """Stop the background cron scheduler."""
    pid = _get_scheduler_pid()

    if not pid:
        console.print("[yellow]Cron scheduler is not running[/yellow]")
        return

    try:
        os.kill(pid, signal.SIGTERM)
        console.print(f"[green]Sent stop signal to cron scheduler[/green] (PID {pid})")

        import time
        for _ in range(10):
            time.sleep(0.2)
            if not _get_scheduler_pid():
                console.print("[green]Cron scheduler stopped[/green]")
                return

        console.print("[yellow]Scheduler may still be shutting down...[/yellow]")
    except ProcessLookupError:
        console.print("[yellow]Scheduler process not found[/yellow]")
        PID_FILE.unlink(missing_ok=True)
    except PermissionError:
        console.print(f"[red]Permission denied[/red] to stop PID {pid}")


def cmd_cron_clear(args: argparse.Namespace) -> None:
    """Clear all scheduled jobs."""
    service = CronService(storage_path=settings.get_cron_storage_path())
    jobs = service.list_jobs()

    if not jobs:
        console.print("[yellow]No jobs to clear[/yellow]")
        return

    if not args.yes:
        console.print(f"[yellow]This will delete {len(jobs)} jobs.[/yellow]")
        response = console.input("Continue? [y/N]: ").strip().lower()
        if response != "y":
            console.print("[dim]Aborted[/dim]")
            return

    for job in jobs:
        service.delete_job(job.id)

    console.print(f"[green]Cleared {len(jobs)} jobs[/green]")


# Memory commands
def parse_time_range(time_str: str) -> tuple[int, int]:
    """Parse a time range string like '1h', '30m', '2d' into hours and minutes.

    Args:
        time_str: Time string (e.g., '1h', '30m', '2d', '1h30m')

    Returns:
        Tuple of (hours, minutes)

    Raises:
        ValueError: If the format is invalid
    """
    import re

    time_str = time_str.lower().strip()
    hours = 0
    minutes = 0

    # Match patterns like 1h, 30m, 2d, 1h30m
    pattern = r'(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?'
    match = re.fullmatch(pattern, time_str)

    if not match or not any(match.groups()):
        raise ValueError(f"Invalid time format: {time_str}. Use format like 1h, 30m, 2d, 1h30m")

    days, hrs, mins = match.groups()
    if days:
        hours += int(days) * 24
    if hrs:
        hours += int(hrs)
    if mins:
        minutes += int(mins)

    return hours, minutes


def cmd_memory_reset(args: argparse.Namespace) -> None:
    """Reset memory entries from a specified time range."""
    from macbot.memory import AgentMemory

    try:
        hours, minutes = parse_time_range(args.time_range)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    total_minutes = hours * 60 + minutes
    if total_minutes <= 0:
        console.print("[red]Error:[/red] Time range must be positive")
        sys.exit(1)

    memory = AgentMemory()

    # Show what will be deleted
    time_desc = ""
    if hours > 0:
        time_desc += f"{hours}h"
    if minutes > 0:
        time_desc += f"{minutes}m"

    if not args.yes:
        console.print(f"[yellow]This will delete all memory entries from the last {time_desc}.[/yellow]")
        response = console.input("Continue? [y/N]: ").strip().lower()
        if response != "y":
            console.print("[dim]Aborted[/dim]")
            return

    result = memory.clear_recent_records(hours=hours, minutes=minutes)

    console.print(f"[green]Cleared {result['total']} records:[/green]")
    console.print(f"  Emails: {result['emails_deleted']}")
    console.print(f"  Reminders: {result['reminders_deleted']}")


def cmd_memory_show(args: argparse.Namespace) -> None:
    """Show memory contents and statistics."""
    from macbot.memory import AgentMemory

    memory = AgentMemory()

    days = args.days or 7
    summary = memory.get_summary(days=days)

    console.print(f"\n[bold]Agent Memory[/bold] (last {days} days)\n")
    console.print(f"  Emails processed: {summary['emails_processed']}")
    console.print(f"  Reminders created: {summary['reminders_created']}")

    if summary['actions_breakdown']:
        console.print("\n  Actions breakdown:")
        for action, count in sorted(summary['actions_breakdown'].items()):
            console.print(f"    {action}: {count}")

    if args.verbose:
        console.print(f"\n[dim]Database: {memory.db_path}[/dim]")

        # Show recent entries
        emails = memory.get_processed_emails(limit=10, days=days)
        if emails:
            console.print(f"\n[bold]Recent processed emails:[/bold]")
            for email in emails:
                console.print(f"  [{email['processed_at'][:16]}] {email['subject'][:50]}")
                console.print(f"    Action: {email['action_taken'] or 'reviewed'}")


def cmd_memory_clear(args: argparse.Namespace) -> None:
    """Clear all memory entries."""
    from macbot.memory import AgentMemory

    memory = AgentMemory()

    if not args.yes:
        summary = memory.get_summary(days=9999)
        total = summary['emails_processed'] + summary['reminders_created']
        console.print(f"[yellow]This will delete ALL {total} memory entries.[/yellow]")
        response = console.input("Continue? [y/N]: ").strip().lower()
        if response != "y":
            console.print("[dim]Aborted[/dim]")
            return

    # Delete everything by using a very large time range
    result = memory.clear_recent_records(hours=999999)
    console.print(f"[green]Cleared all memory ({result['total']} records)[/green]")


# Telegram commands
TELEGRAM_PID_FILE = MACBOT_DIR / "telegram.pid"
TELEGRAM_LOG_FILE = MACBOT_DIR / "telegram.log"


def _get_telegram_pid() -> int | None:
    """Get the PID of a running Telegram service, or None if not running."""
    if not TELEGRAM_PID_FILE.exists():
        return None
    try:
        pid = int(TELEGRAM_PID_FILE.read_text().strip())
        os.kill(pid, 0)
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        TELEGRAM_PID_FILE.unlink(missing_ok=True)
        return None


def cmd_telegram_start(args: argparse.Namespace) -> None:
    """Start the Telegram service."""
    from macbot.telegram import TelegramService

    if not settings.telegram_bot_token:
        console.print("[red]Error:[/red] MACBOT_TELEGRAM_BOT_TOKEN not set")
        console.print("  1. Create a bot via @BotFather on Telegram")
        console.print("  2. Set the token: export MACBOT_TELEGRAM_BOT_TOKEN='your-token'")
        sys.exit(1)

    # Check if already running
    existing_pid = _get_telegram_pid()
    if existing_pid and args.daemon:
        console.print(f"[yellow]Telegram service already running[/yellow] (PID {existing_pid})")
        console.print("Stop it first with: macbot telegram stop")
        sys.exit(1)

    # Validate token first
    async def _validate() -> tuple[bool, str]:
        from macbot.telegram.bot import validate_token
        return await validate_token(settings.telegram_bot_token)

    ok, msg = asyncio.run(_validate())
    if not ok:
        console.print(f"[red]Invalid token:[/red] {msg}")
        sys.exit(1)

    console.print(f"[green]Connected as {msg}[/green]")

    if not settings.telegram_chat_id:
        console.print("[yellow]Warning:[/yellow] MACBOT_TELEGRAM_CHAT_ID not set")
        console.print("  Run 'macbot telegram whoami' to get your chat ID")

    if args.daemon:
        # Background mode
        console.print(f"\n[green]Starting Telegram service in background...[/green]")
        console.print(f"  Log: {TELEGRAM_LOG_FILE}")
        console.print(f"\nUse 'macbot telegram stop' to stop")

        _daemonize()

        # Update PID file location for telegram
        TELEGRAM_PID_FILE.write_text(str(os.getpid()))

        # Redirect to telegram log
        log_fd = os.open(str(TELEGRAM_LOG_FILE), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        os.dup2(log_fd, sys.stdout.fileno())
        os.dup2(log_fd, sys.stderr.fileno())
        os.close(log_fd)

        print(f"\n{'='*60}")
        print(f"MacBot Telegram Service started at {datetime.now().isoformat()}")
        print(f"PID: {os.getpid()}")
        print(f"{'='*60}\n")

        def handle_signal(signum, frame):
            print(f"\nReceived signal {signum}, shutting down...")
            TELEGRAM_PID_FILE.unlink(missing_ok=True)
            sys.exit(0)

        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)

        # Create service and run
        service = TelegramService(
            bot_token=settings.telegram_bot_token,
            chat_id=settings.telegram_chat_id or None,
            allowed_users=settings.telegram_allowed_users or None,
        )

        registry = create_default_registry()
        agent = Agent(registry)

        async def message_handler(text: str, chat_id: str) -> str:
            print(f"\n[{datetime.now().isoformat()}] Message from {chat_id}: {text[:50]}...")
            try:
                result = await agent.run(text, stream=False)
                print(f"Response: {result[:100]}...")
                return result
            except Exception as e:
                print(f"Error: {e}")
                return f"Error: {e}"

        service.set_message_handler(message_handler)

        try:
            asyncio.run(service.start(write_pid=False))
        finally:
            TELEGRAM_PID_FILE.unlink(missing_ok=True)

    else:
        # Foreground mode
        console.print(f"\n[dim]Starting Telegram service (press Ctrl+C to stop)...[/dim]\n")

        service = TelegramService(
            bot_token=settings.telegram_bot_token,
            chat_id=settings.telegram_chat_id or None,
            allowed_users=settings.telegram_allowed_users or None,
        )

        registry = create_default_registry()
        agent = Agent(registry)

        async def message_handler(text: str, chat_id: str) -> str:
            console.print(f"\n[bold blue]Message from {chat_id}:[/bold blue] {text}")
            try:
                result = await agent.run(text, stream=False)
                console.print(f"[bold green]Response:[/bold green] {result[:500]}{'...' if len(result) > 500 else ''}")
                return result
            except Exception as e:
                console.print(f"[red]Error:[/red] {e}")
                return f"Error: {e}"

        service.set_message_handler(message_handler)

        try:
            asyncio.run(service.start())
        except KeyboardInterrupt:
            console.print("\n[dim]Telegram service stopped.[/dim]")


def cmd_telegram_stop(args: argparse.Namespace) -> None:
    """Stop the Telegram service daemon."""
    pid = _get_telegram_pid()

    if not pid:
        console.print("[yellow]Telegram service is not running[/yellow]")
        return

    try:
        os.kill(pid, signal.SIGTERM)
        console.print(f"[green]Sent stop signal to Telegram service[/green] (PID {pid})")

        import time
        for _ in range(10):
            time.sleep(0.2)
            if not _get_telegram_pid():
                console.print("[green]Telegram service stopped[/green]")
                return

        console.print("[yellow]Service may still be shutting down...[/yellow]")
    except ProcessLookupError:
        console.print("[yellow]Telegram service process not found[/yellow]")
        TELEGRAM_PID_FILE.unlink(missing_ok=True)
    except PermissionError:
        console.print(f"[red]Permission denied[/red] to stop PID {pid}")


def cmd_telegram_status(args: argparse.Namespace) -> None:
    """Check the status of the Telegram service."""
    pid = _get_telegram_pid()

    if pid:
        console.print(f"[green]Telegram service is running[/green] (PID {pid})")
        console.print(f"  Log file: {TELEGRAM_LOG_FILE}")

        if TELEGRAM_LOG_FILE.exists():
            console.print(f"\n[dim]Recent log entries:[/dim]")
            lines = TELEGRAM_LOG_FILE.read_text().strip().split("\n")
            for line in lines[-10:]:
                console.print(f"  {line}")
    else:
        console.print("[yellow]Telegram service is not running[/yellow]")

    # Show configuration status
    console.print(f"\n[bold]Configuration:[/bold]")
    if settings.telegram_bot_token:
        masked = settings.telegram_bot_token[:8] + "..." + settings.telegram_bot_token[-4:]
        console.print(f"  Token: {masked}")
    else:
        console.print(f"  Token: [red]Not set[/red]")

    if settings.telegram_chat_id:
        console.print(f"  Chat ID: {settings.telegram_chat_id}")
    else:
        console.print(f"  Chat ID: [yellow]Not set[/yellow]")


def cmd_telegram_send(args: argparse.Namespace) -> None:
    """Send a test message via Telegram."""
    from macbot.telegram import TelegramBot

    if not settings.telegram_bot_token:
        console.print("[red]Error:[/red] MACBOT_TELEGRAM_BOT_TOKEN not set")
        sys.exit(1)

    chat_id = args.chat_id or settings.telegram_chat_id
    if not chat_id:
        console.print("[red]Error:[/red] No chat ID provided")
        console.print("  Use --chat-id or set MACBOT_TELEGRAM_CHAT_ID")
        sys.exit(1)

    async def _send() -> None:
        bot = TelegramBot(settings.telegram_bot_token)
        try:
            await bot.send_message(chat_id, args.message)
            console.print(f"[green]Message sent to {chat_id}[/green]")
        except Exception as e:
            console.print(f"[red]Failed to send:[/red] {e}")
            sys.exit(1)
        finally:
            await bot.close()

    asyncio.run(_send())


def cmd_telegram_whoami(args: argparse.Namespace) -> None:
    """Help the user get their chat ID."""
    from macbot.telegram import TelegramBot

    if not settings.telegram_bot_token:
        console.print("[red]Error:[/red] MACBOT_TELEGRAM_BOT_TOKEN not set")
        sys.exit(1)

    console.print("[bold]Getting your chat ID...[/bold]\n")
    console.print("1. Open Telegram and send any message to your bot")
    console.print("2. Your chat ID will appear below\n")
    console.print("[dim]Press Ctrl+C to stop[/dim]\n")

    async def _whoami() -> None:
        bot = TelegramBot(settings.telegram_bot_token)
        info = await bot.get_me()
        console.print(f"Bot: @{info['username']}")
        console.print("Waiting for messages...\n")

        seen_chats: set[int] = set()
        offset = None

        try:
            while True:
                updates = await bot.get_updates(offset=offset, timeout=30)
                for update in updates:
                    offset = update.update_id + 1
                    if update.message:
                        chat_id = update.message.chat_id
                        if chat_id not in seen_chats:
                            seen_chats.add(chat_id)
                            user = update.message.from_user
                            user_info = f"@{user.username}" if user and user.username else str(user.id) if user else "Unknown"
                            console.print(f"[green]Found![/green] Chat ID: [bold]{chat_id}[/bold] (from {user_info})")
                            console.print(f"\nSet it with:")
                            console.print(f"  export MACBOT_TELEGRAM_CHAT_ID='{chat_id}'")
        except asyncio.CancelledError:
            pass
        finally:
            await bot.close()

    try:
        asyncio.run(_whoami())
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped.[/dim]")


def main() -> NoReturn:
    """Main entry point for MacBot CLI."""
    # Check for --help-all before argparse processes it
    show_all_commands = "--help-all" in sys.argv

    # Handle custom help output for clean display (only for top-level help)
    is_top_level_help = (
        ("-h" in sys.argv or "--help" in sys.argv) and
        len([a for a in sys.argv[1:] if not a.startswith("-")]) == 0
    ) or (show_all_commands and len(sys.argv) == 2)

    if is_top_level_help:
        if show_all_commands:
            console.print(f"""[bold]macbot[/bold] v{__version__} - LLM-powered agent for macOS automation

[bold]MAIN COMMANDS[/bold]
  run          Run a goal or ask a question
  start        Start the macbot service (cron + telegram)
  stop         Stop the macbot service
  status       Check service status
  doctor       Check system prerequisites
  onboard      Interactive setup wizard

[bold]ADMIN COMMANDS[/bold]
  chat         Interactive chat with the agent
  task         Execute a task directly (no LLM)
  tasks        List available tasks
  cron         Manage scheduled jobs
  memory       Manage agent memory
  telegram     Telegram bot commands
  version      Show version information

[bold]OPTIONS[/bold]
  -v, --verbose    Show detailed output
  --help-all       Show all commands

[bold]EXAMPLES[/bold]
  macbot run "Check my emails"        Run a goal
  macbot start -d                     Start service as daemon
  macbot cron import jobs.yaml        Import scheduled jobs
  macbot telegram whoami              Get your Telegram chat ID
""")
        else:
            console.print(f"""[bold]macbot[/bold] v{__version__} - LLM-powered agent for macOS automation

[bold]COMMANDS[/bold]
  run          Run a goal or ask a question
  start        Start the macbot service (cron + telegram)
  stop         Stop the macbot service
  status       Check service status
  doctor       Check system prerequisites
  onboard      Interactive setup wizard

[bold]OPTIONS[/bold]
  -v, --verbose    Show detailed output
  --help-all       Show all commands including admin tools

[bold]GETTING STARTED[/bold]
  macbot onboard                      Setup wizard (recommended for new users)
  macbot run "Check my emails"        Run a goal
  macbot doctor                       Verify setup

Use [bold]macbot --help-all[/bold] to see all commands.
Use [bold]macbot <command> --help[/bold] for command details.
""")
        sys.exit(0)

    parser = argparse.ArgumentParser(
        prog="macbot",
        description="MacBot - LLM-powered agent for macOS automation",
        add_help=False,  # We handle help ourselves
    )
    parser.add_argument("-h", "--help", action="store_true", help="Show help")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show detailed output")
    parser.add_argument("--help-all", action="store_true", help="Show all commands")

    subparsers = parser.add_subparsers(dest="command")

    # ==========================================================================
    # MAIN COMMANDS (shown in default help)
    # ==========================================================================

    # Run command (single goal)
    run_parser = subparsers.add_parser(
        "run",
        help="Run a goal or ask a question",
        description="Give the agent a goal to achieve. The agent will reason "
                    "about it and call tasks as needed.",
        epilog="""Examples:
  macbot run "Check my emails"              Run a goal
  macbot run "What's on my calendar?"       Ask a question
  macbot run --list-jobs                    Show available jobs"""
    )
    run_parser.add_argument(
        "goal", nargs="?", default=None,
        help="Natural language goal or job name from ~/.macbot/jobs.yaml"
    )
    run_parser.add_argument(
        "--list-jobs", action="store_true",
        help="List available jobs from ~/.macbot/jobs.yaml"
    )
    run_parser.add_argument(
        "-c", "--continue", dest="continue_chat", action="store_true",
        help="Continue to interactive chat after completing the goal"
    )
    run_parser.add_argument(
        "--no-stream", dest="no_stream", action="store_true",
        help="Disable streaming output (wait for complete response)"
    )
    run_parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Show detailed output including tool calls"
    )
    run_parser.add_argument(
        "--debug", action="store_true",
        help="Show debug output (script commands, full errors)"
    )
    run_parser.set_defaults(func=cmd_run)

    # Start command (unified service)
    start_parser = subparsers.add_parser(
        "start",
        help="Start the macbot service (cron + telegram)",
        description="Start the unified macbot service that runs scheduled jobs "
                    "and listens for Telegram messages."
    )
    start_parser.add_argument(
        "-d", "--daemon", action="store_true",
        help="Run in background as a daemon"
    )
    start_parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Show detailed output"
    )
    start_parser.set_defaults(func=cmd_start)

    # Stop command
    stop_parser = subparsers.add_parser(
        "stop",
        help="Stop the macbot service",
        description="Stop the running macbot service daemon."
    )
    stop_parser.set_defaults(func=cmd_stop)

    # Status command
    status_parser = subparsers.add_parser(
        "status",
        help="Check service status",
        description="Show the status of the macbot service, cron jobs, and Telegram."
    )
    status_parser.set_defaults(func=cmd_status)

    # Doctor command
    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Check system prerequisites and configuration",
        description="Verify that MacBot is properly configured and all "
                    "prerequisites are met."
    )
    doctor_parser.set_defaults(func=cmd_doctor)

    # Onboard command
    onboard_parser = subparsers.add_parser(
        "onboard",
        help="Interactive setup wizard for new users",
        description="Step-by-step guide to set up MacBot: configure LLM provider, "
                    "grant macOS permissions, set up Telegram, and verify everything works."
    )
    onboard_parser.set_defaults(func=cmd_onboard)

    # ==========================================================================
    # ADMIN COMMANDS (hidden from default help, shown with --help-all)
    # ==========================================================================

    # Chat command (interactive mode)
    chat_parser = subparsers.add_parser(
        "chat",
        help=argparse.SUPPRESS,  # Admin command
        description="Start an interactive conversation with the agent. "
                    "Context is preserved between messages."
    )
    chat_parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Show detailed output including tool calls"
    )
    chat_parser.set_defaults(func=cmd_chat)

    # Task command (direct execution)
    task_parser = subparsers.add_parser(
        "task",
        help=argparse.SUPPRESS,  # Admin command
        description="Execute a specific task directly without LLM involvement. "
                    "Useful for testing or scripting.",
        epilog="Example: macbot task get_unread_emails count_only=true"
    )
    task_parser.add_argument(
        "task_name",
        help="Name of the task to execute"
    )
    task_parser.add_argument(
        "args", nargs="*",
        help="Task arguments as key=value pairs"
    )
    task_parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Show detailed output"
    )
    task_parser.set_defaults(func=cmd_task)

    # Tasks command (list tasks)
    tasks_parser = subparsers.add_parser(
        "tasks",
        help=argparse.SUPPRESS,  # Admin command
        description="Show all tasks (tools) the agent can use."
    )
    tasks_parser.set_defaults(func=cmd_tasks)

    # Also allow 'list' as alias for 'tasks'
    list_parser = subparsers.add_parser(
        "list",
        help=argparse.SUPPRESS  # Always hidden (it's just an alias)
    )
    list_parser.set_defaults(func=cmd_tasks)

    # Schedule command group (legacy, hidden)
    schedule_parser = subparsers.add_parser(
        "schedule",
        help=argparse.SUPPRESS,  # Hidden - use 'start' instead
        description="Run a goal or task on a repeating schedule. "
                    "Can run in foreground or as a background daemon.",
        epilog="""Examples:
  macbot schedule --goal "Check emails" --interval 300
  macbot schedule --goal "Check emails" --interval 300 --background
  macbot schedule status
  macbot schedule stop
  macbot schedule log --follow"""
    )
    schedule_subparsers = schedule_parser.add_subparsers(dest="schedule_command")

    # Default: run a schedule (when no subcommand given, uses these args)
    schedule_parser.add_argument(
        "--goal",
        help="Goal to run (uses LLM reasoning)"
    )
    schedule_parser.add_argument(
        "--task",
        help="Task to run (direct execution, no LLM)"
    )
    schedule_parser.add_argument(
        "--interval", type=int, default=60,
        help="Seconds between runs (default: 60)"
    )
    schedule_parser.add_argument(
        "-b", "--background", action="store_true",
        help="Run in background as a daemon"
    )
    schedule_parser.set_defaults(func=cmd_schedule)

    # schedule status
    schedule_status = schedule_subparsers.add_parser(
        "status",
        help="Check if background scheduler is running"
    )
    schedule_status.set_defaults(func=cmd_schedule_status)

    # schedule stop
    schedule_stop = schedule_subparsers.add_parser(
        "stop",
        help="Stop the background scheduler"
    )
    schedule_stop.set_defaults(func=cmd_schedule_stop)

    # schedule log
    schedule_log = schedule_subparsers.add_parser(
        "log",
        help="View scheduler log"
    )
    schedule_log.add_argument(
        "-f", "--follow", action="store_true",
        help="Follow log output (like tail -f)"
    )
    schedule_log.add_argument(
        "-n", "--lines", type=int, default=50,
        help="Number of lines to show (default: 50)"
    )
    schedule_log.set_defaults(func=cmd_schedule_log)

    # Version command
    version_parser = subparsers.add_parser(
        "version",
        help=argparse.SUPPRESS  # Admin command
    )
    version_parser.set_defaults(func=cmd_version)

    # Cron command group
    cron_parser = subparsers.add_parser(
        "cron",
        help=argparse.SUPPRESS,  # Admin command
        description="Create and manage persistent scheduled jobs that can run "
                    "at specific times or intervals."
    )
    cron_subparsers = cron_parser.add_subparsers(dest="cron_command", metavar="SUBCOMMAND")

    # cron add
    cron_add = cron_subparsers.add_parser("add", help="Create a new scheduled job")
    cron_add.add_argument("--name", required=True, help="Job name")
    cron_add.add_argument("--message", required=True, help="Goal or message to process")
    cron_add.add_argument("--description", help="Job description")
    cron_add.add_argument("--at", help="Run once at datetime (ISO: YYYY-MM-DDTHH:MM:SS)")
    cron_add.add_argument("--every", type=int, help="Run every N seconds")
    cron_add.add_argument("--cron", help="Cron expression (e.g., '0 9 * * *')")
    cron_add.add_argument("--timezone", default="UTC", help="Timezone for cron")
    cron_add.add_argument("--agent", action="store_true", help="Process with LLM agent")
    cron_add.add_argument("--disabled", action="store_true", help="Create in disabled state")
    cron_add.set_defaults(func=cmd_cron_add)

    # cron list
    cron_list = cron_subparsers.add_parser("list", help="List scheduled jobs")
    cron_list.set_defaults(func=cmd_cron_list)

    # cron run
    cron_run = cron_subparsers.add_parser("run", help="Run a job immediately")
    cron_run.add_argument("job_id", help="Job ID")
    cron_run.set_defaults(func=cmd_cron_run)

    # cron remove
    cron_remove = cron_subparsers.add_parser("remove", help="Remove a job")
    cron_remove.add_argument("job_id", help="Job ID")
    cron_remove.set_defaults(func=cmd_cron_remove)

    # cron enable
    cron_enable = cron_subparsers.add_parser("enable", help="Enable a job")
    cron_enable.add_argument("job_id", help="Job ID")
    cron_enable.set_defaults(func=cmd_cron_enable)

    # cron disable
    cron_disable = cron_subparsers.add_parser("disable", help="Disable a job")
    cron_disable.add_argument("job_id", help="Job ID")
    cron_disable.set_defaults(func=cmd_cron_disable)

    # cron import
    cron_import = cron_subparsers.add_parser(
        "import",
        help="Import jobs from a YAML configuration file",
        description="Import jobs from a YAML file. This stops any running scheduler, "
                    "clears existing jobs, and imports the new jobs.",
        epilog="""YAML file format:
  jobs:
    - name: "Email Check"
      goal: "Check my emails and summarize urgent ones"
      interval: 300  # seconds

    - name: "Morning Briefing"
      goal: |
        Give me a morning briefing:
        - Unread emails
        - Today's calendar
        - Overdue reminders
      cron: "0 9 * * *"
      timezone: "America/New_York"

    - name: "One-time Reminder"
      goal: "Remind me about the meeting"
      at: "2026-02-01T14:00:00"
      enabled: false"""
    )
    cron_import.add_argument("file", help="Path to YAML configuration file")
    cron_import.set_defaults(func=cmd_cron_import)

    # cron start
    cron_start = cron_subparsers.add_parser(
        "start",
        help="Start scheduler to run all registered jobs",
        description="Start the cron scheduler to execute all enabled jobs. "
                    "Jobs must be imported first with 'macbot cron import'."
    )
    cron_start.add_argument(
        "-b", "--background", action="store_true",
        help="Run in background as a daemon"
    )
    cron_start.set_defaults(func=cmd_cron_start)

    # cron stop
    cron_stop = cron_subparsers.add_parser(
        "stop",
        help="Stop the background cron scheduler"
    )
    cron_stop.set_defaults(func=cmd_cron_stop)

    # cron clear
    cron_clear = cron_subparsers.add_parser(
        "clear",
        help="Clear all scheduled jobs"
    )
    cron_clear.add_argument(
        "-y", "--yes", action="store_true",
        help="Skip confirmation"
    )
    cron_clear.set_defaults(func=cmd_cron_clear)

    # Memory command group
    memory_parser = subparsers.add_parser(
        "memory",
        help=argparse.SUPPRESS,  # Admin command
        description="View and manage the agent's persistent memory that tracks "
                    "processed emails and created reminders."
    )
    memory_subparsers = memory_parser.add_subparsers(dest="memory_command", metavar="SUBCOMMAND")

    # memory show
    memory_show = memory_subparsers.add_parser(
        "show",
        help="Show memory statistics and recent entries",
        description="Display statistics about what the agent has processed."
    )
    memory_show.add_argument(
        "--days", type=int, default=7,
        help="Number of days to show (default: 7)"
    )
    memory_show.add_argument(
        "-v", "--verbose", action="store_true",
        help="Show detailed entries"
    )
    memory_show.set_defaults(func=cmd_memory_show)

    # memory reset
    memory_reset = memory_subparsers.add_parser(
        "reset",
        help="Clear recent memory entries",
        description="Delete memory entries from the specified time range. "
                    "Use this to re-process emails that were recently handled.",
        epilog="""Time format examples:
  1h      Last 1 hour
  30m     Last 30 minutes
  2d      Last 2 days
  1h30m   Last 1 hour 30 minutes

Example:
  macbot memory reset 1h      # Clear entries from last hour"""
    )
    memory_reset.add_argument(
        "time_range",
        help="Time range to clear (e.g., 1h, 30m, 2d, 1h30m)"
    )
    memory_reset.add_argument(
        "-y", "--yes", action="store_true",
        help="Skip confirmation"
    )
    memory_reset.set_defaults(func=cmd_memory_reset)

    # memory clear
    memory_clear = memory_subparsers.add_parser(
        "clear",
        help="Clear ALL memory entries",
        description="Delete all memory entries. Use with caution."
    )
    memory_clear.add_argument(
        "-y", "--yes", action="store_true",
        help="Skip confirmation"
    )
    memory_clear.set_defaults(func=cmd_memory_clear)

    # Telegram command group
    telegram_parser = subparsers.add_parser(
        "telegram",
        help=argparse.SUPPRESS,  # Admin command
        description="Receive tasks and send results via Telegram.",
        epilog="""Setup:
  1. Create a bot via @BotFather on Telegram
  2. export MACBOT_TELEGRAM_BOT_TOKEN='your-token'
  3. macbot telegram whoami  # Get your chat ID
  4. export MACBOT_TELEGRAM_CHAT_ID='your-chat-id'
  5. macbot telegram start

Examples:
  macbot telegram start        Start in foreground
  macbot telegram start -d     Start as daemon
  macbot telegram status       Check service status
  macbot telegram stop         Stop the daemon
  macbot telegram send "Hi"    Send a test message"""
    )
    telegram_subparsers = telegram_parser.add_subparsers(dest="telegram_command", metavar="SUBCOMMAND")

    # telegram start
    telegram_start = telegram_subparsers.add_parser(
        "start",
        help="Start the Telegram service",
        description="Start listening for Telegram messages and respond with agent results."
    )
    telegram_start.add_argument(
        "-d", "--daemon", action="store_true",
        help="Run in background as a daemon"
    )
    telegram_start.set_defaults(func=cmd_telegram_start)

    # telegram stop
    telegram_stop = telegram_subparsers.add_parser(
        "stop",
        help="Stop the Telegram service daemon"
    )
    telegram_stop.set_defaults(func=cmd_telegram_stop)

    # telegram status
    telegram_status = telegram_subparsers.add_parser(
        "status",
        help="Check Telegram service status"
    )
    telegram_status.set_defaults(func=cmd_telegram_status)

    # telegram send
    telegram_send = telegram_subparsers.add_parser(
        "send",
        help="Send a test message",
        description="Send a message to verify Telegram is working."
    )
    telegram_send.add_argument(
        "message",
        help="Message to send"
    )
    telegram_send.add_argument(
        "--chat-id",
        help="Target chat ID (uses default if not specified)"
    )
    telegram_send.set_defaults(func=cmd_telegram_send)

    # telegram whoami
    telegram_whoami = telegram_subparsers.add_parser(
        "whoami",
        help="Get your chat ID",
        description="Helps you find your Telegram chat ID by listening for messages."
    )
    telegram_whoami.set_defaults(func=cmd_telegram_whoami)

    args = parser.parse_args()
    setup_logging(args.verbose)

    # No command given - show welcome
    if args.command is None:
        console.print(Markdown(WELCOME_TEXT))
        sys.exit(0)

    # Handle schedule subcommands
    if args.command == "schedule":
        if hasattr(args, 'schedule_command') and args.schedule_command is not None:
            # A subcommand like 'status', 'stop', 'log' was given
            args.func(args)
        elif not args.goal and not args.task:
            # No subcommand and no --goal/--task: show help
            schedule_parser.print_help()
            sys.exit(0)
        else:
            # Has --goal or --task: run the scheduler
            args.func(args)
        sys.exit(0)

    # Handle cron subcommands
    if args.command == "cron" and args.cron_command is None:
        cron_parser.print_help()
        sys.exit(0)

    # Handle memory subcommands
    if args.command == "memory" and args.memory_command is None:
        memory_parser.print_help()
        sys.exit(0)

    # Handle telegram subcommands
    if args.command == "telegram" and args.telegram_command is None:
        telegram_parser.print_help()
        sys.exit(0)

    args.func(args)
    sys.exit(0)


if __name__ == "__main__":
    main()
