---
id: clawhub
name: ClawHub
description: Search, install, and manage community skills from the ClawHub registry.
tasks:
  - run_shell_command
examples:
  - "Search ClawHub for a Slack skill"
  - "Install the weather skill from ClawHub"
  - "Update all my ClawHub skills"
  - "What skills are available for home automation?"
  - "Show me my installed ClawHub skills"
  - "Uninstall the twitter skill"
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

### After Installing a Skill
After installing a skill from ClawHub, always run `son skills enrich <skill-id>` to add task mappings, examples, and behavior notes. Without enrichment, the skill will only have basic metadata and won't guide the agent effectively.

### If ClawHub Is Not Installed
If the `clawhub` command is not found, install it first:
```
npm install -g clawhub
```

### Acting Autonomously
When the user asks to search for or install a skill, just do it. Don't ask for confirmation before searching. Only confirm before installing (since it writes to disk).
