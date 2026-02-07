# Skills (AgentSkills compatible)

Skills provide guidance for handling specific types of requests. Son of Simon comes with built-in skills for Mail, Calendar, Reminders, Notes, Safari, and Browser Automation. You can enable or disable skills, customize built-in ones, or create your own.

<p align="center">
  <img src="images/skills-list.png" alt="Skills List" width="500">
</p>

Each skill defines:
- Which apps and tasks it uses
- Example prompts that trigger it
- Safe defaults to prevent mistakes
- Actions that require your confirmation

## Custom skills

Custom skills are saved to `~/.macbot/skills/`. Skills use the **AgentSkills standard** (the same SKILL.md format used by OpenClaw, Claude Code, and Cursor) so you can drop in skills from any compatible tool and they just work.

## Install skills from ClawHub

[ClawHub](https://clawhub.ai) is a community registry of agent skills. You can browse and install skills directly by asking the agent:

> "Search ClawHub for a Slack skill"
> "Install https://clawhub.ai/steipete/slack"

The agent will install the skill and automatically enrich it with task mappings and behavior notes so it works out of the box. You can also use the CLI:

```bash
npm install -g clawhub                              # one-time setup
clawhub search slack                                 # find skills
clawhub install --dir ~/.macbot/skills slack          # install
son skills enrich slack                              # enrich with AI
```

## CLI commands

```bash
son skills                  # List all skills
son skills list             # Same as above
son skills show <id>        # Show skill details
son skills enable <id>      # Enable a skill
son skills disable <id>     # Disable a skill
```

Add `--json` for dashboard integration.
