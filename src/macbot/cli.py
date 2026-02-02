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

# Help text shown when no command is given
WELCOME_TEXT = f"""
# MacBot v{__version__}

An LLM-powered agent for macOS automation.

## Quick Start

```bash
macbot chat                              # Interactive conversation
macbot run "Check my emails" -c          # Run goal, then chat
macbot run "What's on my calendar?"      # Run goal and exit
macbot task get_unread_emails            # Execute task directly
macbot tasks                             # List available tasks
```

## Concepts

| Concept | What it is | Example |
|---------|------------|---------|
| **Task** | Single action, no LLM | `macbot task get_today_events` |
| **Goal** | Natural language → LLM reasons → calls tasks | `macbot run "Summarize my emails"` |
| **Chat** | Interactive conversation, context preserved | `macbot chat` |
| **Job** | Goal + Schedule = automatic execution | `macbot cron start -b` |

**Task vs Goal**: A task is a specific tool (like `get_unread_emails`). A goal is
what you want to achieve ("check my emails and flag urgent ones")—the agent
figures out which tasks to call.

**Job**: Wraps a goal with a schedule to run it automatically. Define jobs in a
YAML file and import them with `macbot cron import jobs.yaml`, then start the
scheduler with `macbot cron start`.

Use `macbot <command> --help` for detailed help.
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
    # Enable debug logging if --debug flag is set
    if getattr(args, "debug", False):
        setup_logging(verbose=True)
        console.print("[dim]Debug mode enabled[/dim]\n")

    registry = create_default_registry()
    agent = Agent(registry)

    async def _run() -> None:
        # Execute the initial goal
        stream = not getattr(args, "no_stream", False)
        verbose = args.verbose or getattr(args, "debug", False)

        if verbose and not stream:
            console.print(Panel(f"[bold]Goal:[/bold] {args.goal}", title="Running"))

        result = await agent.run(args.goal, verbose=verbose, stream=stream)

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


def main() -> NoReturn:
    """Main entry point for MacBot CLI."""
    parser = argparse.ArgumentParser(
        prog="macbot",
        description="MacBot - LLM-powered agent for macOS automation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
CONCEPTS:
  Task    A single executable action (tool). No LLM involved.
          Example: get_unread_emails, create_reminder, get_today_events
          Usage: macbot task <name> [key=value ...]

  Goal    Natural language objective. LLM reasons about which tasks to call.
          Example: "Check my emails and summarize urgent ones"
          Usage: macbot run "<goal>"

  Chat    Interactive conversation. Context preserved between messages.
          Usage: macbot chat

  Job     A goal that runs automatically on a schedule.
          Job = Goal + Schedule (interval, cron, or one-time)
          Define jobs in a YAML file, import with 'macbot cron import'

EXAMPLES:
  macbot chat                              Interactive chat
  macbot run "Check my emails" -c          Run goal, then continue chatting
  macbot run "What meetings today?"        Run goal and exit
  macbot task get_today_events             Execute task directly
  macbot cron import jobs.yaml             Import jobs from config file
  macbot cron start -b                     Start scheduler in background
  macbot cron list                         List registered jobs
  macbot cron stop                         Stop background scheduler
"""
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Show detailed output including tool calls"
    )

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    # Chat command (interactive mode)
    chat_parser = subparsers.add_parser(
        "chat",
        help="Start interactive chat with the agent",
        description="Start an interactive conversation with the agent. "
                    "Context is preserved between messages."
    )
    chat_parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Show detailed output including tool calls"
    )
    chat_parser.set_defaults(func=cmd_chat)

    # Run command (single goal)
    run_parser = subparsers.add_parser(
        "run",
        help="Run a goal (with optional continue to chat)",
        description="Give the agent a goal to achieve. The agent will reason "
                    "about it and call tasks as needed.",
        epilog="Example: macbot run \"Check my emails and summarize urgent ones\" -c"
    )
    run_parser.add_argument(
        "goal",
        help="Natural language goal for the agent"
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

    # Task command (direct execution)
    task_parser = subparsers.add_parser(
        "task",
        help="Execute a task directly (no LLM)",
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
        help="List available tasks",
        description="Show all tasks (tools) the agent can use."
    )
    tasks_parser.set_defaults(func=cmd_tasks)

    # Also allow 'list' as alias for 'tasks'
    list_parser = subparsers.add_parser(
        "list",
        help="List available tasks (alias for 'tasks')"
    )
    list_parser.set_defaults(func=cmd_tasks)

    # Schedule command group
    schedule_parser = subparsers.add_parser(
        "schedule",
        help="Run scheduled jobs (foreground or background)",
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
        help="Show version information"
    )
    version_parser.set_defaults(func=cmd_version)

    # Doctor command
    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Check system prerequisites and configuration",
        description="Verify that MacBot is properly configured and all "
                    "prerequisites are met."
    )
    doctor_parser.set_defaults(func=cmd_doctor)

    # Cron command group
    cron_parser = subparsers.add_parser(
        "cron",
        help="Manage scheduled jobs (persistent)",
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

    args.func(args)
    sys.exit(0)


if __name__ == "__main__":
    main()
