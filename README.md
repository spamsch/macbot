# MacBot

An LLM-powered agent for macOS automation. MacBot uses the ReAct (Reasoning + Acting) pattern to achieve goals by reasoning about what to do and executing tasks in a loop.

## Features

- **Interactive Chat**: Conversational interface with context preserved
- **Goal-Driven Agent**: Give natural language objectives, agent figures out how
- **macOS Integration**: Built-in tasks for Mail, Calendar, Reminders, Notes, Safari
- **Background Scheduling**: Run goals or tasks automatically on a schedule
- **Multiple LLM Providers**: Anthropic Claude and OpenAI supported

## Quick Start

```bash
# Install
pip install -e ".[dev]"

# Start interactive chat
macbot chat

# Run a goal
macbot run "What's on my calendar today?"

# Run a goal, then continue chatting
macbot run "Check my emails" --continue
```

## Concepts

MacBot has four core concepts. Understanding these is key to using it effectively.

### Task

A **task** is a single, atomic action the agent can execute. Tasks are like tools or functions—they have a name, parameters, and return a result. **No LLM reasoning is involved** when executing a task directly.

```bash
# Execute a task directly (no LLM)
macbot task get_unread_emails
macbot task create_reminder title="Call dentist" due="2026-02-01"
macbot task get_today_events calendar="Work"
```

Tasks are deterministic: same inputs → same outputs. Examples:
- `get_unread_emails` - Fetch unread emails from Mail.app
- `create_reminder` - Create a reminder in Reminders.app
- `get_system_info` - Get OS and hardware information

### Goal

A **goal** is a natural language objective you give to the agent. The agent uses an LLM to **reason** about how to achieve the goal, deciding which tasks to call and in what order. The agent loops until the goal is complete or max iterations reached.

```bash
# Run a goal (LLM reasons about what tasks to call)
macbot run "Check my emails and summarize any urgent ones"
macbot run "Create a reminder to call John tomorrow at 3pm"
macbot run "What meetings do I have this week?"
```

Goals are flexible: the agent interprets your intent and figures out the steps.

**Goal vs Task comparison:**

| Aspect | Task | Goal |
|--------|------|------|
| Input | Structured parameters | Natural language |
| LLM involved | No | Yes |
| Deterministic | Yes | No (LLM decides) |
| Use case | Scripting, automation | Interactive, complex requests |
| Example | `get_today_events` | "What's on my schedule?" |

### Chat

**Chat** is an interactive conversation mode where you can have an ongoing dialogue with the agent. Context is preserved between messages, so you can ask follow-up questions.

```bash
# Start interactive chat
macbot chat

# Or run a goal and continue chatting
macbot run "Check my emails" --continue
```

In chat mode:
- Type messages to chat with the agent
- Type `clear` to reset conversation context
- Type `tasks` to see available tasks
- Type `quit` to exit

### Job

A **job** is a scheduled execution of a goal. Jobs run automatically at specified intervals or times, either in the foreground or as a background daemon.

**Job = Goal + Schedule**

Jobs are defined in a YAML configuration file and imported into MacBot:

```yaml
# jobs.yaml
jobs:
  - name: "Email Monitor"
    goal: "Check my emails and alert me about urgent ones"
    interval: 300  # every 5 minutes

  - name: "Morning Briefing"
    goal: |
      Give me a morning briefing:
      - Unread emails
      - Today's calendar
      - Overdue reminders
    cron: "0 9 * * *"  # 9am daily
    timezone: "America/New_York"
```

```bash
# Import jobs from configuration file
macbot cron import jobs.yaml

# Start the scheduler (background)
macbot cron start -b

# Check status
macbot cron list

# Stop the scheduler
macbot cron stop
```

Jobs are for automation—things you want to happen repeatedly without manual intervention.

**When to use each:**

| Want to... | Use |
|------------|-----|
| Do something once, interactively | `macbot run "..."` or `macbot chat` |
| Do something once, scripted | `macbot task <name>` |
| Do something repeatedly | `macbot schedule` |

## Installation

```bash
# Clone and install
cd macbot
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Configuration

Create a `.env` file:

```bash
# LLM Provider (anthropic or openai)
MACBOT_LLM_PROVIDER=anthropic

# Anthropic settings
MACBOT_ANTHROPIC_API_KEY=your-api-key
MACBOT_ANTHROPIC_MODEL=claude-sonnet-4-20250514

# OpenAI settings (if using OpenAI)
MACBOT_OPENAI_API_KEY=your-api-key
MACBOT_OPENAI_MODEL=gpt-4o

# Agent settings
MACBOT_MAX_ITERATIONS=10
```

## Command Reference

### `macbot chat`

Start an interactive conversation with the agent.

```bash
macbot chat
macbot chat -v  # Verbose: show tool calls
```

### `macbot run <goal>`

Run a single goal.

```bash
macbot run "What's on my calendar today?"
macbot run "Check my emails" -c        # Continue to chat after
macbot run "Create a reminder" -v      # Verbose output
```

### `macbot task <name> [args]`

Execute a task directly without LLM involvement.

```bash
macbot task get_unread_emails
macbot task get_unread_emails count_only=true
macbot task create_reminder title="Test" due="2026-02-01"
macbot task search_emails sender="amazon" limit=5
```

### `macbot tasks`

List available tasks.

```bash
macbot tasks      # Grouped by category
macbot tasks -v   # Detailed with parameters
```

### `macbot schedule`

Run a goal or task on a repeating schedule.

```bash
# Foreground (Ctrl+C to stop)
macbot schedule --goal "Check emails" --interval 300
macbot schedule --task get_unread_emails --interval 60

# Background daemon
macbot schedule --goal "Check emails" --interval 300 --background

# Management commands
macbot schedule status    # Check if running
macbot schedule stop      # Stop background scheduler
macbot schedule log       # View log (last 50 lines)
macbot schedule log -f    # Follow log (tail -f style)
macbot schedule log -n 100  # Last 100 lines
```

### `macbot cron`

Manage scheduled jobs (stored in `~/.macbot/cron.json`).

```bash
# Import jobs from YAML configuration file
macbot cron import jobs.yaml

# Start the scheduler (runs all enabled jobs)
macbot cron start          # Foreground (Ctrl+C to stop)
macbot cron start -b       # Background daemon

# Stop background scheduler
macbot cron stop

# List all jobs
macbot cron list

# Run a specific job immediately
macbot cron run <job_id>

# Enable/disable jobs
macbot cron enable <job_id>
macbot cron disable <job_id>

# Remove a job
macbot cron remove <job_id>

# Clear all jobs
macbot cron clear
```

#### Job Configuration File Format

Create a YAML file to define your jobs:

```yaml
# jobs.yaml
jobs:
  # Interval-based job (runs every N seconds)
  - name: "Email Check"
    goal: "Check my emails and summarize urgent ones"
    interval: 300
    description: "Check emails every 5 minutes"

  # Cron-based job (runs on schedule)
  - name: "Morning Briefing"
    goal: |
      Give me a morning briefing with:
      - Unread email summary
      - Today's calendar events
      - Reminders due today
    cron: "0 9 * * *"
    timezone: "America/New_York"

  # One-time job (runs once at specified time)
  - name: "Deadline Reminder"
    goal: "Remind me about the project deadline"
    at: "2026-02-15T09:00:00"
    enabled: false

# Job fields:
#   name: Job name (required)
#   goal: Natural language goal (required)
#   interval: Seconds between runs (OR)
#   cron: Cron expression (OR)
#   at: ISO datetime for one-time execution
#   timezone: Timezone for cron (default: UTC)
#   description: Optional description
#   enabled: Whether active (default: true)
```

## Available Tasks

MacBot includes 27 built-in tasks:

### Mail (Apple Mail.app)
- `get_unread_emails` - Get unread email summary
- `search_emails` - Search by sender/subject
- `send_email` - Send an email
- `mark_emails_read` - Mark emails as read

### Calendar (Apple Calendar.app)
- `get_today_events` - Today's events
- `get_week_events` - Upcoming events
- `create_calendar_event` - Create an event
- `list_calendars` - List calendars

### Reminders (Apple Reminders.app)
- `get_due_today_reminders` - Reminders due today
- `create_reminder` - Create a reminder
- `complete_reminder` - Mark complete
- `list_reminders` - List with filters

### Notes (Apple Notes.app)
- `create_note` - Create a note
- `search_notes` - Search notes
- `list_notes` - List notes

### Safari
- `get_current_safari_page` - Current tab info
- `open_url_in_safari` - Open a URL
- `extract_safari_links` - Extract page links
- `list_safari_tabs` - List open tabs

### System
- `get_system_info` - OS/hardware info
- `get_current_time` - Current time
- `read_file` - Read a file
- `write_file` - Write a file
- `run_shell_command` - Run shell command
- `fetch_url` - Fetch web content

## Examples

### Daily Briefing

```bash
macbot run "Give me a morning briefing: unread emails, today's calendar, and overdue reminders"
```

### Email Triage

```bash
macbot run "Check my emails, summarize anything urgent, and mark newsletters as read"
```

### Meeting Prep

```bash
macbot run "What meetings do I have today? Create a reminder 15 minutes before each one"
```

### Research and Save

```bash
macbot run "Open apple.com in Safari, extract the main navigation links, and save them to a note called 'Apple Site Map'"
```

### Background Monitoring

```bash
# Create a jobs file
cat > my-jobs.yaml << 'EOF'
jobs:
  - name: "Boss Email Alert"
    goal: "Check for emails from my boss and alert me if any are urgent"
    interval: 300
  - name: "Calendar Reminder"
    goal: "Check if I have any meetings in the next 15 minutes and remind me"
    interval: 600
EOF

# Import and start
macbot cron import my-jobs.yaml
macbot cron start -b

# Check status
macbot cron list

# Stop when done
macbot cron stop
```

## Architecture

```
src/macbot/
├── cli.py                 # Command-line interface
├── config.py              # Configuration
├── core/
│   ├── agent.py           # ReAct agent loop
│   ├── scheduler.py       # Job scheduling
│   └── task.py            # Task base classes
├── providers/
│   ├── anthropic.py       # Claude provider
│   └── openai.py          # OpenAI provider
└── tasks/
    ├── macos_automation.py  # Mail, Calendar, etc.
    ├── shell_command.py     # Shell execution
    ├── file_read.py         # File operations
    └── ...
```

## Creating Custom Tasks

### Method 1: Subclass Task

```python
from macbot.tasks.base import Task

class MyTask(Task):
    @property
    def name(self) -> str:
        return "my_task"

    @property
    def description(self) -> str:
        return "Does something useful"

    async def execute(self, param1: str, param2: int = 10) -> dict:
        return {"result": f"Processed {param1} with {param2}"}

# Register
registry.register(MyTask())
```

### Method 2: Function Task

```python
from macbot.tasks.base import FunctionTask

def add_numbers(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

registry.register(FunctionTask(
    func=add_numbers,
    name="add",
    description="Add two integers"
))
```

### Method 3: Decorator

```python
@registry.task(description="Multiply two numbers")
def multiply(a: float, b: float) -> float:
    return a * b
```

## Files and Directories

| Path | Purpose |
|------|---------|
| `~/.macbot/` | MacBot data directory |
| `~/.macbot/cron.json` | Registered jobs (import with `macbot cron import`) |
| `~/.macbot/scheduler.pid` | Background scheduler PID file |
| `~/.macbot/scheduler.log` | Background scheduler log |
| `examples/jobs.yaml` | Example job configuration file |

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check .

# Type check
mypy src/macbot
```

## License

MIT License
