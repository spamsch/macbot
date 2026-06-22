"""Tasks: Agent Memory

Provides tools for the agent to track what it has done - processed emails,
created reminders, etc. Uses a SQLite database for persistence.

Also provides tools for managing knowledge memory - lessons learned, user
preferences, and user facts stored in YAML format.
"""

import json
from typing import Any

from macbot.memory import AgentMemory, KnowledgeMemory
from macbot.tasks.base import Task

# Singleton memory instances
_memory: AgentMemory | None = None
_knowledge: KnowledgeMemory | None = None


def get_memory() -> AgentMemory:
    """Get the shared memory instance."""
    global _memory
    if _memory is None:
        _memory = AgentMemory()
    return _memory


def get_knowledge() -> KnowledgeMemory:
    """Get the shared knowledge memory instance."""
    global _knowledge
    if _knowledge is None:
        _knowledge = KnowledgeMemory()
    return _knowledge


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


class MemoryAddLessonTask(Task):
    """Add a lesson learned to knowledge memory."""

    @property
    def name(self) -> str:
        return "memory_add_lesson"

    @property
    def description(self) -> str:
        return (
            "Add a lesson learned to persistent memory. Use this to remember techniques, "
            "workarounds, or important discoveries that should be recalled in future sessions. "
            "If a lesson with the same topic exists, it will be updated."
        )

    async def execute(
        self,
        topic: str,
        lesson: str,
        domain: str = "",
        importance: int = 3,
    ) -> dict[str, Any]:
        """Add a lesson learned.

        Args:
            topic: Short topic identifier (e.g., "React inputs", "Booking.com automation")
            lesson: The lesson content describing what was learned
            domain: Coarse area this belongs to (finances, mail, calendar, documents,
                health, travel, coding, contacts, general). Helps scoped recall.
            importance: 1-5; 5 = essential and permanent. Lower-importance auto
                lessons may be expired during cleanup.

        Returns:
            Dictionary with result
        """
        knowledge = get_knowledge()
        knowledge.add_lesson(topic, lesson, domain=domain or None, importance=importance)
        return {
            "success": True,
            "topic": topic,
            "lesson": lesson,
            "message": f"Lesson added for topic: {topic}",
        }


class MemorySetPreferenceTask(Task):
    """Set a user preference in knowledge memory."""

    @property
    def name(self) -> str:
        return "memory_set_preference"

    @property
    def description(self) -> str:
        return (
            "Set or update a user preference in persistent memory. Use this to remember "
            "how the user likes things done - output format, default values, personal preferences. "
            "Replaces any existing preference in the same category."
        )

    async def execute(
        self,
        category: str,
        preference: str,
        domain: str = "",
        importance: int = 3,
    ) -> dict[str, Any]:
        """Set a user preference.

        Args:
            category: Category of preference (e.g., "output", "hotels", "communication")
            preference: The preference description
            domain: Coarse area this belongs to (finances, mail, calendar, documents,
                health, travel, coding, contacts, general). Helps scoped recall.
            importance: 1-5; 5 = essential and permanent.

        Returns:
            Dictionary with result
        """
        knowledge = get_knowledge()
        knowledge.set_preference(
            category, preference, domain=domain or None, importance=importance,
        )
        return {
            "success": True,
            "category": category,
            "preference": preference,
            "message": f"Preference set for category: {category}",
        }


class MemoryAddFactTask(Task):
    """Add a fact about the user to knowledge memory."""

    @property
    def name(self) -> str:
        return "memory_add_fact"

    @property
    def description(self) -> str:
        return (
            "Add a fact about the user to persistent memory. Use this to remember "
            "personal information that might be relevant in future interactions - "
            "location, language, time zone, etc. Skips if the exact fact already exists."
        )

    async def execute(
        self,
        fact: str,
        domain: str = "",
        importance: int = 3,
    ) -> dict[str, Any]:
        """Add a user fact.

        Args:
            fact: The fact to remember (e.g., "Lives in Germany", "Prefers metric units")
            domain: Coarse area this belongs to (finances, mail, calendar, documents,
                health, travel, coding, contacts, general). Helps scoped recall.
            importance: 1-5; 5 = essential and permanent.

        Returns:
            Dictionary with result
        """
        knowledge = get_knowledge()
        knowledge.add_fact(fact, domain=domain or None, importance=importance)
        return {
            "success": True,
            "fact": fact,
            "message": f"Fact added: {fact}",
        }


class MemoryListTask(Task):
    """List current knowledge memory contents."""

    @property
    def name(self) -> str:
        return "memory_list"

    @property
    def description(self) -> str:
        return (
            "List all current knowledge memory contents - lessons learned, user preferences, "
            "and user facts. Use this to see what has been remembered across sessions."
        )

    async def execute(self) -> dict[str, Any]:
        """List all knowledge memory.

        Returns:
            Dictionary with all memory contents
        """
        knowledge = get_knowledge()
        data = knowledge.get_all()
        return {
            "success": True,
            "lessons_learned": data.get("lessons_learned", []),
            "user_preferences": data.get("user_preferences", []),
            "user_facts": data.get("user_facts", []),
        }


class SearchFilesWrittenTask(Task):
    """Search for files that were written by the agent."""

    @property
    def name(self) -> str:
        return "search_files_written"

    @property
    def description(self) -> str:
        return (
            "Search for files that were written by the agent. "
            "Use this to recall documents - e.g., 'I worked on a document for Frank' "
            "or 'What reports did I create last week?'. Searches filenames and summaries."
        )

    async def execute(
        self,
        query: str | None = None,
        days: int | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search for written files.

        Args:
            query: Search term (searches filename and summary)
            days: Only show files from last N days
            limit: Maximum number of results

        Returns:
            Dictionary with matching files
        """
        memory = get_memory()
        files = memory.search_files_written(query=query, days=days, limit=limit)
        return {
            "success": True,
            "count": len(files),
            "query": query,
            "files": files,
        }


class MemoryRemoveLessonTask(Task):
    """Remove a lesson from knowledge memory."""

    @property
    def name(self) -> str:
        return "memory_remove_lesson"

    @property
    def description(self) -> str:
        return (
            "Remove a lesson learned from persistent memory by its topic. "
            "Use this to clear outdated or incorrect lessons."
        )

    async def execute(self, topic: str) -> dict[str, Any]:
        """Remove a lesson by topic.

        Args:
            topic: The topic of the lesson to remove

        Returns:
            Dictionary with result
        """
        knowledge = get_knowledge()
        removed = knowledge.remove_lesson(topic)
        return {
            "success": True,
            "topic": topic,
            "removed": removed,
            "message": f"Lesson removed" if removed else f"No lesson found with topic: {topic}",
        }


class MemorySearchTask(Task):
    """Search knowledge memory for items relevant to a topic."""

    @property
    def name(self) -> str:
        return "memory_search"

    @property
    def description(self) -> str:
        return (
            "Search stored knowledge (lessons, preferences, facts) for items "
            "relevant to a topic — e.g. 'finances', 'how the user likes email replies'. "
            "Relevant memories are already injected each turn; use this when you need "
            "to pull more on a specific subject."
        )

    async def execute(
        self,
        query: str,
        domain: str = "",
        limit: int = 10,
    ) -> dict[str, Any]:
        """Search knowledge memory.

        Args:
            query: What to look for (topic, keywords).
            domain: Optional domain to bias toward (finances, mail, etc.).
            limit: Maximum number of results.

        Returns:
            Dictionary with matching memory items.
        """
        knowledge = get_knowledge()
        results = knowledge.search(query, domain=domain or None, limit=limit)
        return {
            "success": True,
            "query": query,
            "count": len(results),
            "results": results,
        }


class RunMemoryMaintenanceTask(Task):
    """Run memory consolidation/cleanup on demand."""

    @property
    def name(self) -> str:
        return "run_memory_maintenance"

    @property
    def description(self) -> str:
        return (
            "Run the memory maintenance (sleep) pass now: distill recent turns into "
            "durable knowledge, merge duplicates, and expire stale memories. "
            "Normally runs automatically overnight; use this to trigger it manually."
        )

    async def execute(self) -> dict[str, Any]:
        """Run the maintenance pass.

        Returns:
            Dictionary with the maintenance report (counts).
        """
        from macbot.memory import run_maintenance

        report = await run_maintenance()
        return {"success": True, "report": report}


def register_memory_tasks(registry) -> None:
    """Register all memory tasks with a registry.

    Args:
        registry: TaskRegistry to register tasks with.
    """
    # Email/reminder tracking tasks (SQLite-based)
    registry.register(CheckEmailProcessedTask())
    registry.register(MarkEmailProcessedTask())
    registry.register(ListProcessedEmailsTask())
    registry.register(RecordReminderCreatedTask())
    registry.register(GetAgentMemorySummaryTask())
    registry.register(SearchFilesWrittenTask())

    # Knowledge memory tasks (YAML-based)
    registry.register(MemoryAddLessonTask())
    registry.register(MemorySetPreferenceTask())
    registry.register(MemoryAddFactTask())
    registry.register(MemoryListTask())
    registry.register(MemoryRemoveLessonTask())
    registry.register(MemorySearchTask())
    registry.register(RunMemoryMaintenanceTask())
