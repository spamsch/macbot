"""Task: Calculator

Perform mathematical calculations.
"""

from macbot.tasks.base import Task
from macbot.tasks.registry import task_registry


class CalculatorTask(Task):
    """Calculate the sum of a list of numbers.

    Example:
        task = CalculatorTask()
        result = await task.execute(numbers=[1, 2, 3, 4, 5])
        # Returns: 15.0
    """

    @property
    def name(self) -> str:
        """Get the task name."""
        return "calculate_sum"

    @property
    def description(self) -> str:
        """Get the task description."""
        return "Calculate the sum of a list of numbers."

    async def execute(self, numbers: list[float]) -> float:
        """Calculate the sum of numbers.

        Args:
            numbers: List of numbers to sum.

        Returns:
            Sum of all numbers.
        """
        # Convert strings to floats (LLM may send strings)
        nums = [float(n) for n in numbers]
        return sum(nums)


# Auto-register on import
task_registry.register(CalculatorTask())
