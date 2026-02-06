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

### Acting Autonomously
When the user asks to search for or install a skill, just do it. Don't ask for confirmation before searching. Only confirm before installing (since it writes to disk).

### Install Workflow
1. If given a URL, extract the slug (e.g., `https://clawhub.ai/steipete/slack` → `slack`)
2. `run_shell_command`: `clawhub install --dir ~/.macbot/skills <slug>`
3. Read the installed SKILL.md with `read_file(path="~/.macbot/skills/<slug>/SKILL.md")` so you know what the skill does and can use it immediately in this conversation
4. Tell the user the skill is installed and ready to use
5. Optionally, offer to enrich the skill with `enrich_skill(skill_id="<skill-id>")` for better examples and behavior notes — but this is not required. Skills work immediately after install.
