# MacBot

An LLM-powered agent for macOS automation. Give natural language commands, MacBot figures out the rest.

## Features

- **macOS Automation** - Control Mail, Calendar, Reminders, Notes, and Safari via natural language
- **Telegram Integration** - Send commands and receive responses remotely with conversation context
- **Paperless-ngx Integration** - Search, upload, and download documents from your paperless instance
- **Scheduled Jobs** - Run automated tasks on intervals or cron schedules
- **Browser Automation** - ARIA-based web interaction with screenshots and element detection
- **Multiple LLM Providers** - OpenAI (GPT-5.2) or Anthropic (Claude)

## Quick Start

```bash
# Install
pip install -e .

# Interactive setup wizard
macbot onboard

# Run a goal
macbot run "Check my emails and summarize urgent ones"

# Start service (Telegram + cron jobs)
macbot start
```

## Commands

| Command | Description |
|---------|-------------|
| `macbot run "<goal>"` | Run a natural language goal |
| `macbot chat` | Interactive conversation mode |
| `macbot start` | Start service (Telegram + cron) |
| `macbot stop` | Stop the service |
| `macbot status` | Check service status |
| `macbot doctor` | Verify setup and permissions |
| `macbot onboard` | Interactive setup wizard |
| `macbot tasks` | List available tasks |
| `macbot cron list` | List scheduled jobs |

## Configuration

Run `macbot onboard` for interactive setup, or create `~/.macbot/.env`:

```bash
# LLM Provider
MACBOT_LLM_PROVIDER=openai
MACBOT_OPENAI_API_KEY=sk-...
MACBOT_OPENAI_MODEL=gpt-5.2

# Or use Anthropic
# MACBOT_LLM_PROVIDER=anthropic
# MACBOT_ANTHROPIC_API_KEY=sk-ant-...

# Telegram (optional)
MACBOT_TELEGRAM_BOT_TOKEN=123456:ABC...
MACBOT_TELEGRAM_CHAT_ID=your_chat_id

# Paperless-ngx (optional)
MACBOT_PAPERLESS_URL=http://localhost:8000
MACBOT_PAPERLESS_API_TOKEN=your_token

# Agent settings
MACBOT_MAX_ITERATIONS=100
```

## Available Tasks

**Mail** - `search_emails`, `send_email`, `move_email`, `mark_emails_read`, `download_attachments`

**Calendar** - `get_today_events`, `get_week_events`, `create_calendar_event`, `list_calendars`

**Reminders** - `create_reminder`, `complete_reminder`, `list_reminders`, `get_due_today_reminders`

**Notes** - `create_note`, `search_notes`, `list_notes`

**Safari** - `get_current_safari_page`, `open_url_in_safari`, `list_safari_tabs`, `extract_safari_links`

**Browser** - `browser_navigate`, `browser_click`, `browser_type`, `browser_screenshot`, `browser_snapshot`

**Paperless** - `paperless_search`, `paperless_upload`, `paperless_download`, `paperless_list_tags`

**Telegram** - `telegram_send`

**System** - `get_system_info`, `read_file`, `write_file`, `run_shell_command`, `fetch_url`

## Scheduled Jobs

Create `jobs.yaml`:

```yaml
jobs:
  - name: "Morning Briefing"
    goal: |
      Give me a morning briefing:
      - Unread emails summary
      - Today's calendar
      - Reminders due today
    cron: "0 9 * * *"
    timezone: "America/New_York"

  - name: "Email Check"
    goal: "Check for urgent emails and notify me via Telegram"
    interval: 300  # every 5 minutes
```

```bash
macbot cron import jobs.yaml
macbot start -d  # Start as daemon
```

## Telegram Usage

1. Create a bot via [@BotFather](https://t.me/BotFather)
2. Run `macbot onboard` to configure
3. Start service: `macbot start`
4. Send messages to your bot

Special commands in Telegram:
- `/reset`, `/clear`, `/new` - Start a fresh conversation

Conversation context is preserved between messages for natural back-and-forth chat.

## Examples

```bash
# Email management
macbot run "Find emails from Amazon this week and list any with tracking numbers"

# Calendar
macbot run "What meetings do I have tomorrow? Create reminders 15 min before each"

# Paperless
macbot run "Search paperless for invoices from 2024"
macbot run "Upload ~/Downloads/receipt.pdf to paperless"

# Browser automation
macbot run "Open google.com, search for 'weather', and take a screenshot"

# Complex workflows
macbot run "Check my emails, archive newsletters, and send me a Telegram summary"
```

## Architecture

```
~/.macbot/
├── .env           # Configuration
├── cron.json      # Scheduled jobs
└── service.log    # Service logs

src/macbot/
├── cli.py         # Command-line interface
├── config.py      # Settings management
├── service.py     # Unified service (cron + telegram)
├── core/
│   └── agent.py   # ReAct agent loop
├── tasks/         # Task implementations
│   ├── macos_automation.py
│   ├── browser_automation.py
│   ├── paperless.py
│   └── telegram.py
└── telegram/      # Telegram integration
```

## License

MIT License
