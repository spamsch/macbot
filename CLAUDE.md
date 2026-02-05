# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Son of Simon is an LLM-powered macOS automation assistant that integrates with built-in Apple apps (Mail, Calendar, Reminders, Notes, Safari) through natural language. It consists of:

- **Python CLI/Service** (`src/macbot/`) - Agent loop, task system, cron scheduler, Telegram bot
- **Tauri Desktop App** (`app/`) - Svelte/TypeScript frontend with Rust backend for onboarding UI
- **macOS Automation Scripts** (`macos-automation/`) - AppleScript bridges to Apple apps

## Common Commands

```bash
# Python development
pip install -e ".[dev]"          # Install with dev dependencies
pytest                           # Run all tests
pytest tests/test_task.py        # Run specific test file
pytest -k "test_name"            # Run tests matching pattern
ruff check src/                  # Lint
mypy src/                        # Type check

# CLI usage
son run "<goal>"                 # Execute natural language goal
son chat                         # Interactive mode
son start                        # Start background service
son doctor                       # Check setup/permissions

# Tauri app (from app/ directory)
npm install                      # Install frontend deps
npm run dev                      # Dev server with hot reload
npm run tauri build              # Build complete app

# Build scripts
./scripts/build-sidecar.sh       # Build PyInstaller binary
./scripts/build-app.sh           # Full build (sidecar + Tauri)
./scripts/release.sh patch       # Bump version, tag, push
```

## Architecture

### Agent Loop (`src/macbot/core/agent.py`)
ReAct-style loop: LLM reasons → calls tools → observes results → repeats. The agent maintains conversation history and tracks token usage.

### Task System (`src/macbot/tasks/`)
- `Task` base class with `name`, `description`, `execute()` method
- Tool schemas auto-generated from type hints
- `TaskRegistry` holds all available tasks
- Tasks return `TaskResult` with success/output/error

### LLM Providers (`src/macbot/providers/`)
- `LLMProvider` abstract base with `create_message()`
- Implementations: `LiteLLMProvider` (100+ models), `AnthropicProvider`, `OpenAIProvider`
- Provider selected via `MACBOT_LLM_PROVIDER` env var

### Configuration (`src/macbot/config.py`)
Pydantic settings loaded from `~/.macbot/.env` with `MACBOT_` prefix. Key settings:
- `MACBOT_LLM_PROVIDER` - `anthropic`, `openai`, or any LiteLLM provider
- `MACBOT_ANTHROPIC_API_KEY`, `MACBOT_OPENAI_API_KEY`
- `MACBOT_TELEGRAM_BOT_TOKEN`, `MACBOT_TELEGRAM_CHAT_ID`

### Skills System (`src/macbot/skills/`)
Skills provide declarative guidance that improves agent reliability through examples, safe defaults, and behavior rules.

**Key distinction:**
- **Tools** = Batteries-included macOS automation (Mail, Calendar, Reminders, Notes, Safari tasks)
- **Skills** = Declarative guidance that improves reliability by providing examples, safe defaults, and behavior rules

**Directories:**
- `skills/` - Built-in skills (shipped with app)
- `~/.macbot/skills/` - User skills (override built-in by id)
- `~/.macbot/skills.json` - Enable/disable state persistence

**SKILL.md Format:** YAML frontmatter with fields: `id`, `name`, `description`, `apps`, `tasks`, `examples`, `safe_defaults`, `confirm_before_write`, `requires_permissions`. Markdown body for detailed behavior notes.

**CLI Commands:**
- `son skills` / `son skills list` - List all skills
- `son skills show <id>` - Show skill details
- `son skills enable <id>` / `son skills disable <id>`
- Add `--json` for dashboard integration

### Service Architecture
`MacbotService` runs cron scheduler + Telegram bot together. Uses PID file at `~/.macbot/service.pid`. Maintains separate agent instances per Telegram chat.

### Tauri Integration
Python sidecar binary (PyInstaller) bundled at `Contents/MacOS/son`. Tauri spawns it via shell plugin. Config in `app/src-tauri/capabilities/default.json`.

## Key Patterns

- **Async everywhere** - All I/O uses async/await
- **Type hints** - mypy strict mode enforced
- **Environment config** - No secrets in code, all via `~/.macbot/.env`
- **AppleScript bridges** - macOS automation via scripts in `macos-automation/`

## Release Process

`scripts/release.sh [major|minor|patch|X.Y.Z]` bumps versions in:
- `pyproject.toml`
- `app/src-tauri/tauri.conf.json`
- `app/package.json`
- `app/src-tauri/Cargo.toml`

Creates git tag and pushes to trigger GitHub Actions build.
