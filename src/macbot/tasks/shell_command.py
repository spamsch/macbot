"""Task: Run Shell Command

Execute shell commands and return the output.
"""

import asyncio
from typing import Any

from macbot.tasks.base import Task
from macbot.tasks.registry import task_registry


class RunShellCommandTask(Task):
    """Execute a shell command and return the output.

    Runs commands asynchronously with configurable timeout.
    Returns stdout, stderr, and return code.

    Example:
        task = RunShellCommandTask()
        result = await task.execute(command="echo hello")
        # Returns: {"return_code": 0, "stdout": "hello", "stderr": ""}
    """

    @property
    def name(self) -> str:
        """Get the task name."""
        return "run_shell_command"

    @property
    def description(self) -> str:
        """Get the task description."""
        return "Execute a shell command and return its output. Use with caution."

    async def execute(self, command: str, timeout: int = 30) -> dict[str, Any]:
        """Execute a shell command.

        Args:
            command: The shell command to execute.
            timeout: Maximum time to wait for command completion in seconds.

        Returns:
            Dictionary containing:
            - return_code: Command exit code (-1 on timeout)
            - stdout: Standard output as string
            - stderr: Standard error as string
        """
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
            return {
                "return_code": process.returncode,
                "stdout": stdout.decode().strip(),
                "stderr": stderr.decode().strip(),
            }
        except asyncio.TimeoutError:
            return {
                "return_code": -1,
                "stdout": "",
                "stderr": f"Command timed out after {timeout} seconds",
            }


# Auto-register on import
task_registry.register(RunShellCommandTask())
