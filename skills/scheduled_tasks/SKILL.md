---
id: scheduled_tasks
name: Scheduled Tasks
description: Create and manage recurring or one-shot scheduled tasks using natural language.
apps: []
tasks:
  - schedule_task
  - list_scheduled_tasks
  - delete_scheduled_task
  - update_scheduled_task
  - run_scheduled_task
essential_tasks:
  - schedule_task
  - list_scheduled_tasks
examples:
  - "Every Monday at 8am, compile a news summary from my emails"
  - "Schedule a daily check of my inbox at 9am"
  - "Remind me every Friday at 5pm to review my weekly goals"
  - "Run a task every 30 minutes to check for urgent emails"
  - "Show my scheduled tasks"
  - "Delete the morning email check task"
  - "Disable the weekly report task"
  - "Run the news summary task now"
safe_defaults:
  timezone: Europe/Berlin
  payload_kind: agent_turn
confirm_before_write:
  - delete scheduled task
  - disable scheduled task
---

## Behavior Notes

### Creating Scheduled Tasks
- Always use the user's local timezone (default: Europe/Berlin)
- Write clear, specific goal messages that the agent can execute autonomously
- Prefer cron expressions for recurring schedules over interval_minutes
- For one-shot tasks, use at_time with an ISO datetime

### Cron Expression Reference

| Pattern | Meaning |
|---------|---------|
| `0 9 * * *` | Daily at 9:00 AM |
| `0 9 * * 1` | Every Monday at 9:00 AM |
| `0 9 * * 1-5` | Weekdays at 9:00 AM |
| `0 8,17 * * *` | Daily at 8:00 AM and 5:00 PM |
| `*/30 * * * *` | Every 30 minutes |
| `0 0 1 * *` | First day of every month at midnight |
| `0 9 * * 0` | Every Sunday at 9:00 AM |
| `0 17 * * 5` | Every Friday at 5:00 PM |

### Natural Language Mapping
- "every morning" -> `0 9 * * *` (daily at 9am)
- "every weekday morning" -> `0 9 * * 1-5`
- "every Monday at 8am" -> `0 8 * * 1`
- "twice a day" -> `0 9,17 * * *` (9am and 5pm)
- "every hour" -> `0 * * * *`
- "every 30 minutes" -> use interval_minutes=30

### Managing Tasks
- Use list_scheduled_tasks to show all tasks before modifying
- When the user says "delete" or "remove" a task, find it by name first
- When disabling, use update_scheduled_task with enabled=false
- run_scheduled_task returns the message for inline execution — execute that goal immediately
