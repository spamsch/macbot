"""Tasks: Agent Memory

Provides tools for the agent to track what it has done - processed emails,
created reminders, etc. Uses a SQLite database for persistence.
"""

import json
from typing import Any

from macbot.memory import AgentMemory
from macbot.tasks.base import Task

# Singleton memory instance
_memory: AgentMemory | None = None


def get_memory() -> AgentMemory:
    """Get the shared memory instance."""
    global _memory
    if _memory is None:
        _memory = AgentMemory()
    return _memory


class CheckEmailProcessedTask(Task):
    """Check if an email has already been processed."""

    @property
    def name(self) -> str:
        return "check_email_processed"

    @property
    def description(self) -> str:
        return (
            "Check if an email has already been processed by the agent. "
            "Use this before processing an email to avoid duplicate work. "
            "Pass the email's message_id (from search results)."
        )

    async def execute(self, message_id: str) -> dict[str, Any]:
        """Check if email was processed.

        Args:
            message_id: The RFC Message-ID of the email

        Returns:
            Dictionary with processed status
        """
        memory = get_memory()
        is_processed = memory.is_email_processed(message_id)
        return {
            "success": True,
            "message_id": message_id,
            "already_processed": is_processed,
        }


class MarkEmailProcessedTask(Task):
    """Mark an email as processed."""

    @property
    def name(self) -> str:
        return "mark_email_processed"

    @property
    def description(self) -> str:
        return (
            "Mark an email as processed by the agent. Call this AFTER taking action on an email "
            "(replying, creating reminder, archiving, etc.). Records the message_id, subject, "
            "sender, and what action was taken."
        )

    async def execute(
        self,
        message_id: str,
        subject: str,
        sender: str,
        action_taken: str,
        account: str = "",
        received_date: str = "",
        notes: str = ""
    ) -> dict[str, Any]:
        """Mark email as processed.

        Args:
            message_id: The RFC Message-ID of the email
            subject: Email subject
            sender: Sender email/name
            action_taken: What was done (e.g., 'replied', 'reminder_created', 'reviewed', 'ignored')
            account: Mail account name
            received_date: When the email was received
            notes: Additional notes

        Returns:
            Dictionary with result
        """
        memory = get_memory()
        is_new = memory.mark_email_processed(
            message_id=message_id,
            subject=subject,
            sender=sender,
            account=account,
            received_date=received_date,
            action_taken=action_taken,
            notes=notes
        )
        return {
            "success": True,
            "message_id": message_id,
            "newly_marked": is_new,
            "action_taken": action_taken,
        }


class ListProcessedEmailsTask(Task):
    """List emails that have been processed."""

    @property
    def name(self) -> str:
        return "list_processed_emails"

    @property
    def description(self) -> str:
        return (
            "List emails that have already been processed by the agent. "
            "Useful for reviewing what's been done or avoiding duplicate work."
        )

    async def execute(
        self,
        limit: int = 20,
        days: int | None = None,
        account: str | None = None
    ) -> dict[str, Any]:
        """List processed emails.

        Args:
            limit: Maximum number of results
            days: Only show emails processed in last N days
            account: Filter by account name

        Returns:
            Dictionary with processed emails
        """
        memory = get_memory()
        emails = memory.get_processed_emails(limit=limit, days=days, account=account)
        return {
            "success": True,
            "count": len(emails),
            "emails": emails,
        }


class RecordReminderCreatedTask(Task):
    """Record that a reminder was created."""

    @property
    def name(self) -> str:
        return "record_reminder_created"

    @property
    def description(self) -> str:
        return (
            "Record that a reminder was created by the agent. Call this AFTER creating a reminder "
            "with create_reminder. Links the reminder to the source email if applicable."
        )

    async def execute(
        self,
        title: str,
        list_name: str = "Reminders",
        source_email_id: str | None = None,
        due_date: str | None = None,
        notes: str = ""
    ) -> dict[str, Any]:
        """Record reminder creation.

        Args:
            title: Reminder title
            list_name: Reminders list name
            source_email_id: Message-ID of email that triggered this reminder
            due_date: Due date if set
            notes: Additional notes

        Returns:
            Dictionary with result
        """
        memory = get_memory()
        record_id = memory.record_reminder_created(
            title=title,
            list_name=list_name,
            source_email_id=source_email_id,
            due_date=due_date,
            notes=notes
        )
        return {
            "success": True,
            "record_id": record_id,
            "title": title,
        }


class GetAgentMemorySummaryTask(Task):
    """Get a summary of what the agent has done."""

    @property
    def name(self) -> str:
        return "get_agent_memory"

    @property
    def description(self) -> str:
        return (
            "Get a summary of what the agent has done recently - processed emails, "
            "created reminders, actions taken. Use this to understand what's already been handled."
        )

    async def execute(self, days: int = 7) -> dict[str, Any]:
        """Get agent activity summary.

        Args:
            days: Number of days to summarize (default: 7)

        Returns:
            Dictionary with summary statistics
        """
        memory = get_memory()
        summary = memory.get_summary(days=days)

        # Also get recent items for context
        recent_emails = memory.get_processed_emails(limit=5, days=days)
        recent_reminders = memory.get_created_reminders(limit=5, days=days)

        return {
            "success": True,
            "summary": summary,
            "recent_emails": recent_emails,
            "recent_reminders": recent_reminders,
        }


def register_memory_tasks(registry) -> None:
    """Register all memory tasks with a registry.

    Args:
        registry: TaskRegistry to register tasks with.
    """
    registry.register(CheckEmailProcessedTask())
    registry.register(MarkEmailProcessedTask())
    registry.register(ListProcessedEmailsTask())
    registry.register(RecordReminderCreatedTask())
    registry.register(GetAgentMemorySummaryTask())
