# Skills Implementation Plan

## Goals
- Add a simple, human-editable skills format that improves macOS automation reliability.
- Make skills discoverable and safe for non-technical users.
- Keep the first version small, stable, and easy to maintain.

## Non-Goals (v1)
- A public marketplace or remote skill downloads.
- Complex dependency graphs between skills.
- Code execution inside skills (skills are declarative only).

## Target Users
- Everyday users who want predictable results for Mail, Calendar, Reminders, Notes, and Safari.
- Power users who want to customize behavior without editing Python.

---

## Phase 1: Define the Skill Format

### 1.1 File Layout
- Built-in skills live in: `skills/<skill_name>/SKILL.md`
- User skills live in: `~/.macbot/skills/<skill_name>/SKILL.md`
- Optional per-skill defaults: `skills/<skill_name>/config.yaml`

### 1.2 SKILL.md Structure (Markdown + YAML front matter)
Front matter fields (required unless noted):
- `name`: Short human-friendly name
- `id`: Unique id (snake_case)
- `description`: One-sentence summary
- `apps`: List of related Apple apps (e.g., `Mail`, `Calendar`)
- `tasks`: List of tool names this skill uses
- `examples`: 3-5 natural language examples
- `safe_defaults`: Defaults that reduce mistakes (e.g., `days=7`)
- `requires_permissions` (optional): e.g., `Mail`, `Calendar`, `Reminders`
- `confirm_before_write` (optional): true/false

Example:

```markdown
---
name: Mail Assistant
id: mail_assistant
description: Find, summarize, and act on emails safely.
apps: [Mail]
tasks: [search_emails, send_email, move_email, download_attachments]
examples:
  - "Summarize unread emails from today"
  - "Find emails from UPS and show tracking numbers"
  - "Archive newsletters from this week"
safe_defaults:
  days: 7
confirm_before_write: true
requires_permissions: [Mail]
---

## Behavior
- Prefer search before any action.
- For destructive actions, ask for confirmation.
- Summaries should be concise and list action items.
```

### 1.3 Validation Rules
- `id` must be unique across all skills.
- `tasks` must exist in `TaskRegistry`.
- If `confirm_before_write` is true, note it in prompt injection.

---

## Phase 2: Skills Loader and Registry

### 2.1 New Module
- `src/macbot/skills/loader.py`

Responsibilities:
- Scan `skills/` and `~/.macbot/skills/` (user skills override built-ins).
- Parse YAML front matter.
- Validate schema and known tasks.
- Expose `Skill` objects to the agent.

### 2.2 Data Model
Add `Skill` model:
- `id`, `name`, `description`, `apps`, `tasks`, `examples`, `safe_defaults`, `confirm_before_write`, `requires_permissions`, `body`

### 2.3 Error Handling
- If a skill fails parsing, log a warning and skip it.
- Do not block app startup if a skill is malformed.

---

## Phase 3: Agent Prompt Integration

### 3.1 Prompt Injection
- Add a compact “Skills” section to the system prompt.
- Include:
  - Name and one-line description.
  - A short list of examples (2-3 max per skill).
  - Any `confirm_before_write` rule.
  - `safe_defaults` as default guidance.

### 3.2 Priority Ordering
- Order skills by relevance to available tools and apps.
- For macOS tasks, prioritize Mail/Calendar/Reminders/Notes/Safari skills.

---

## Phase 4: Map Existing macOS Tasks to Skills

Create the first five built-in skills:
1. `mail_assistant`
2. `calendar_assistant`
3. `reminders_assistant`
4. `notes_assistant`
5. `safari_assistant`

Each skill should provide:
- Safe defaults (e.g., date ranges, “preview before action”).
- Confirmation rules for destructive actions (delete, move, send).
- Example prompts and “how to respond” notes.

---

## Phase 5: CLI Support (Minimal)

Add commands:
- `son skills list` - Show available skills
- `son skills show <id>` - Show details for a skill
- `son skills enable/disable <id>` - Toggle skills

Implementation notes:
- Store enabled/disabled state in `~/.macbot/skills.json`.
- By default, all built-in skills are enabled.

---

## Phase 6: Tests

Add tests for:
- Parsing front matter.
- Validation of missing fields and unknown tasks.
- User skill override behavior.
- Prompt injection output.

---

## Phase 7: Documentation

Update `README.md` with a simple “Skills” section:
- Explain what skills are.
- Show a minimal skill example.
- Point to `~/.macbot/skills` for customization.

Add a template skill:
- `examples/skills/template/SKILL.md`

---

## Acceptance Criteria
- App starts even if a skill file is broken.
- Skills appear in the system prompt and guide behavior.
- Built-in macOS skills improve reliability (fewer missed confirmations).
- Users can add a new skill without editing Python.

---

## Rollout
- Ship the skills loader and 5 built-in skills in v1.
- Add more skills only after real user feedback.

