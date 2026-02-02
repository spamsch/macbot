"""Task: Write File

Write content to a file on the filesystem.
"""

from macbot.tasks.base import Task
from macbot.tasks.registry import task_registry


class WriteFileTask(Task):
    """Write content to a file.

    Writes or appends content to a file at the specified path.

    Example:
        task = WriteFileTask()
        result = await task.execute(path="/tmp/test.txt", content="Hello")
        # Returns: "Successfully wrote 5 characters to /tmp/test.txt"
    """

    @property
    def name(self) -> str:
        """Get the task name."""
        return "write_file"

    @property
    def description(self) -> str:
        """Get the task description."""
        return "Write content to a file at the specified path."

    async def execute(self, path: str, content: str, append: bool = False) -> str:
        """Write content to a file.

        Args:
            path: File path to write to.
            content: Content to write.
            append: If True, append to file instead of overwriting.

        Returns:
            Success message with character count.

        Raises:
            PermissionError: If the file cannot be written.
        """
        mode = "a" if append else "w"
        with open(path, mode) as f:
            f.write(content)
        return f"Successfully wrote {len(content)} characters to {path}"


# Auto-register on import
task_registry.register(WriteFileTask())
