---
id: clawhub
name: ClawHub
description: Search, install, and manage community skills from the ClawHub registry.
tasks:
  - run_shell_command
  - enrich_skill
examples:
  - "Search ClawHub for a Slack skill"
  - "Install the weather skill from ClawHub"
  - "Install https://clawhub.ai/steipete/slack"
  - "Update all my ClawHub skills"
  - "What skills are available for home automation?"
  - "Show me my installed ClawHub skills"
safe_defaults:
  dir: "~/.macbot/skills"
confirm_before_write:
  - install skill
  - update all skills
enriched: true
---

## CRITICAL: Always enrich after installing

After EVERY `clawhub install`, you MUST immediately call the `enrich_skill` tool with the skill ID. This is not optional. Without enrichment, the skill is bare metadata and useless to you. The install is not complete until enrichment finishes. Do NOT tell the user the skill is installed until you have enriched it.

## Behavior Notes

### ClawHub CLI Commands

ClawHub is an npm-based CLI for discovering and installing agent skills. All commands use `clawhub` in the terminal:

- **Search:** `clawhub search <query>` — find skills by keyword
- **Install:** `clawhub install --dir ~/.macbot/skills <skill-name>` — install a skill
- **List installed:** `clawhub list --dir ~/.macbot/skills` — show installed skills
- **Update:** `clawhub update --dir ~/.macbot/skills` — update all installed skills
- **Info:** `clawhub info <skill-name>` — show skill details before installing

### Important: Always use `--dir ~/.macbot/skills`
Son of Simon loads user skills from `~/.macbot/skills/`. Always pass `--dir ~/.macbot/skills` to install/list/update commands so skills land in the right place.

### If ClawHub Is Not Installed
If the `clawhub` command is not found, install it first:
```
npm install -g clawhub
```

### URL Handling
When the user provides a ClawHub URL like `https://clawhub.ai/steipete/slack`, the slug is the **last** path segment only: `slack` (NOT `steipete/slack` — the first segment is the owner, not part of the slug). Use the short slug:
```
clawhub install --dir ~/.macbot/skills slack
```
The skill ID for enrichment is the same short slug (e.g., `slack`).

### Acting Autonomously
When the user asks to search for or install a skill, just do it. Don't ask for confirmation before searching. Only confirm before installing (since it writes to disk).

### Full Install Workflow
1. If given a URL, extract the slug (e.g., `https://clawhub.ai/steipete/slack` → `steipete/slack`)
2. `run_shell_command`: `clawhub install --dir ~/.macbot/skills <slug>`
3. `enrich_skill(skill_id="<skill-id>")` (MANDATORY — do this immediately)
4. Then tell the user the skill is ready
