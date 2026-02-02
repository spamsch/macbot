"""Task: Read File

Read content from a file on the filesystem.
"""

from macbot.tasks.base import Task
from macbot.tasks.registry import task_registry


class ReadFileTask(Task):
    """Read content from a file.

    Reads file content with configurable maximum character limit.

    Example:
        task = ReadFileTask()
        result = await task.execute(path="/tmp/test.txt")
        # Returns file content as string
    """

    @property
    def name(self) -> str:
        """Get the task name."""
        return "read_file"

    @property
    def description(self) -> str:
        """Get the task description."""
        return "Read and return the content of a file."

    async def execute(self, path: str, max_chars: int = 10000) -> str:
        """Read content from a file.

        Args:
            path: File path to read from.
            max_chars: Maximum characters to return.

        Returns:
            File content as string.

        Raises:
            FileNotFoundError: If the file does not exist.
            PermissionError: If the file cannot be read.
        """
        with open(path) as f:
            content = f.read(max_chars)
        return content


# Auto-register on import
task_registry.register(ReadFileTask())
