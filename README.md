<p align="center">
  <img src="assets/logo-observer.svg" alt="Son of Simon" width="200" height="200">
</p>

<h1 align="center">Son of Simon</h1>

<p align="center">
  <em>Your personal Mac assistant. Built-in apps. Voice messages. No setup headaches.</em>
</p>

---

## What is this?

Son of Simon is an AI assistant for macOS that works directly with your built-in Apple apps — Mail, Calendar, Reminders, Notes, and Safari. Think of it as the macOS automation layer that OpenClaw is missing.

Where tools like OpenClaw need browser scraping or OAuth flows to access Gmail or Office 365, Son of Simon uses Apple's native app integration. Just add your account in Apple Mail or Calendar and the agent can use it. No tokens, no OAuth, no browser automation needed.

Son of Simon is also more secure in practice because it does not run a separate gateway service. There is no always-on gateway process to expose or configure, which reduces the attack surface compared to a gateway-based setup like OpenClaw.

Skills are compatible with the [AgentSkills standard](https://agentskills.io) used by OpenClaw, Claude Code, and Cursor — so community skills work across tools.

You do not need to code. Download the app, sign in, and start asking.

## What it can do

- Summarize your inbox and find important emails
- Create calendar events and reminders
- Search your notes
- Open and control Safari tabs
- Fill out simple web forms (bookings, purchases, etc.)
- Send and receive messages over Telegram (text or voice)
- Run daily or weekly routines (optional)

## How it works (simple version)

- It uses your built-in Apple apps instead of screen scraping
- It uses the browser only when it has to
- It can listen to your Telegram voice messages if you want remote control

## Get started (most people)

1. Download the latest `.dmg` from Releases
2. Drag Son of Simon to your Applications folder
3. Open it and follow the setup steps

The setup wizard will guide you through:
- Connecting your AI provider (OpenAI, Anthropic, or another provider)
- Granting macOS permissions
- Optional Telegram setup

<p align="center">
  <img src="docs/images/dashboard.png" alt="Dashboard" width="500">
</p>

## Skills (AgentSkills compatible)

Skills provide guidance for handling specific types of requests. Son of Simon comes with built-in skills for Mail, Calendar, Reminders, Notes, Safari, and Browser Automation. You can enable or disable skills, customize built-in ones, or create your own.

<p align="center">
  <img src="docs/images/skills-list.png" alt="Skills List" width="500">
</p>

Each skill defines:
- Which apps and tasks it uses
- Example prompts that trigger it
- Safe defaults to prevent mistakes
- Actions that require your confirmation

<p align="center">
  <img src="docs/images/skill-detail.png" alt="Skill Detail" width="500">
</p>

Custom skills are saved to `~/.macbot/skills/`. Skills use the **AgentSkills standard** (the same SKILL.md format used by OpenClaw, Claude Code, and Cursor) so you can drop in skills from any compatible tool and they just work. You can also use skills from https://clawhub.ai/.

## Requirements

- macOS
- Apple apps configured (Mail, Calendar, Reminders)
- Internet access for your AI provider
- Optional: Telegram bot for remote access

## Privacy and safety

- Your email, calendar, and reminders stay in Apple apps
- The assistant sends prompts to your AI provider to understand your request
- If you enable Telegram, messages go through Telegram
- Local data is stored in `~/.macbot` (settings, logs, and memory)

## OpenClaw vs Son of Simon

|  | Son of Simon | OpenClaw |
|---|---|---|
| **Platform** | macOS only | Cross-platform |
| **Apple apps** | Native (Mail, Calendar, Reminders, Notes, Safari) | Limited (iMessage via imsg) |
| **Gmail / Office 365** | Just add account in Apple Mail/Calendar | Browser flow or OAuth setup |
| **Setup** | Single app with guided wizard | Gateway + configuration |
| **Skills format** | AgentSkills standard (compatible) | AgentSkills standard (compatible) |
| **Messaging** | Telegram | WhatsApp, Telegram, Slack, Discord, Signal, iMessage, etc. |

**Use Son of Simon if** you want deep macOS automation that works with your built-in Apple apps out of the box, no OAuth or browser scraping needed. Skills are cross-compatible — you can use OpenClaw community skills in Son of Simon and vice versa.

**Use OpenClaw if** you want a cross-platform hub with many messaging channels and don't mind extra setup.

## Optional extras

- Paperless-ngx integration for documents
- Time tracking
- Scheduled jobs (daily or hourly tasks)

## Advanced (run from source)

If you want to run Son of Simon from this repository:

```bash
pip install -e .
son onboard
son run "Check my emails and summarize urgent ones"
```

Common commands:

| Command | Description |
|---------|-------------|
| `son run "<goal>"` | Run a natural language goal |
| `son chat` | Interactive chat mode |
| `son start` | Start background service (Telegram + cron) |
| `son doctor` | Verify setup and permissions |

## License

MIT License
