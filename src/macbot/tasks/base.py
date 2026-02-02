"""Base task class for the modular task system.

Tasks are the building blocks that LLMs can use to perform actions.
Each task has a clear interface with name, description, parameters, and return type.
"""

import inspect
from abc import ABC, abstractmethod
from typing import Any, Callable, TypeVar, get_type_hints

from pydantic import BaseModel, Field

T = TypeVar("T")


class TaskParameter(BaseModel):
    """Describes a parameter for a task.

    Attributes:
        name: Parameter name.
        type: Parameter type as a string (e.g., 'string', 'integer').
        description: What this parameter does.
        required: Whether the parameter is required.
        default: Default value if not required.
    """

    name: str = Field(..., description="Parameter name")
    type: str = Field(..., description="Parameter type (e.g., 'string', 'integer')")
    description: str = Field(..., description="What this parameter does")
    required: bool = Field(default=True, description="Whether the parameter is required")
    default: Any = Field(default=None, description="Default value if not required")


class TaskDefinition(BaseModel):
    """Complete definition of a task for LLM consumption.

    Attributes:
        name: Unique task name.
        description: What this task does.
        parameters: List of task parameters.
        returns: Return type description.
    """

    name: str = Field(..., description="Unique task name")
    description: str = Field(..., description="What this task does")
    parameters: list[TaskParameter] = Field(
        default_factory=list, description="Task parameters"
    )
    returns: str = Field(default="string", description="Return type description")


class TaskResult(BaseModel):
    """Result from executing a task.

    Attributes:
        success: Whether the task succeeded.
        output: Task output on success.
        error: Error message if failed.
    """

    success: bool = Field(..., description="Whether the task succeeded")
    output: Any = Field(default=None, description="Task output")
    error: str | None = Field(default=None, description="Error message if failed")


class Task(ABC):
    """Base class for all tasks.

    Tasks should be:
    - Self-documenting with clear descriptions
    - Type-safe with defined parameters and return types
    - Easy for LLMs to understand and use

    Example:
        class MyTask(Task):
            name = "my_task"
            description = "Does something useful"

            async def execute(self, param1: str, param2: int = 10) -> str:
                return f"Processed {param1} with {param2}"
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this task."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human/LLM-readable description of what this task does."""
        ...

    @abstractmethod
    async def execute(self, **kwargs: Any) -> Any:
        """Execute the task with the given parameters.

        Args:
            **kwargs: Task-specific parameters

        Returns:
            Task result
        """
        ...

    def get_parameters(self) -> list[TaskParameter]:
        """Get parameter definitions from the execute method signature.

        Returns:
            List of TaskParameter objects describing the task parameters.
        """
        sig = inspect.signature(self.execute)
        hints = get_type_hints(self.execute)
        params = []

        for param_name, param in sig.parameters.items():
            if param_name in ("self", "kwargs"):
                continue

            param_type = hints.get(param_name, Any)
            type_name = getattr(param_type, "__name__", str(param_type))

            params.append(
                TaskParameter(
                    name=param_name,
                    type=type_name,
                    description=f"Parameter: {param_name}",
                    required=param.default == inspect.Parameter.empty,
                    default=None if param.default == inspect.Parameter.empty else param.default,
                )
            )

        return params

    def to_definition(self) -> TaskDefinition:
        """Convert this task to a definition for LLM consumption.

        Returns:
            TaskDefinition containing the task's full specification.
        """
        return TaskDefinition(
            name=self.name,
            description=self.description,
            parameters=self.get_parameters(),
        )

    def to_tool_schema(self) -> dict[str, Any]:
        """Convert to a tool schema compatible with LLM APIs.

        Returns a schema that works with both Anthropic and OpenAI tool formats.

        Returns:
            Dictionary containing the tool schema.
        """
        properties: dict[str, Any] = {}
        required: list[str] = []

        # Map Python types to JSON Schema types
        type_mapping = {
            "str": "string",
            "int": "integer",
            "float": "number",
            "bool": "boolean",
            "list": "array",
            "dict": "object",
        }

        for param in self.get_parameters():
            prop: dict[str, Any] = {"description": param.description}

            param_type = param.type.lower()

            # Handle generic types like list[float], dict[str, Any]
            if param_type.startswith("list"):
                prop["type"] = "array"
                # Extract inner type if present (e.g., "list[float]" -> "float")
                if "[" in param_type and "]" in param_type:
                    inner_type = param_type[param_type.index("[") + 1 : param_type.index("]")]
                    inner_json_type = type_mapping.get(inner_type, "string")
                    prop["items"] = {"type": inner_json_type}
                else:
                    # Default to string items if no inner type specified
                    prop["items"] = {"type": "string"}
            elif param_type.startswith("dict"):
                prop["type"] = "object"
            else:
                prop["type"] = type_mapping.get(param_type, "string")

            if param.default is not None:
                prop["default"] = param.default

            properties[param.name] = prop

            if param.required:
                required.append(param.name)

        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }


class FunctionTask(Task):
    """Create a task from a simple function.

    This allows quick creation of tasks without subclassing.

    Example:
        def add_numbers(a: int, b: int) -> int:
            return a + b

        task = FunctionTask(add_numbers, description="Add two numbers")
    """

    def __init__(
        self,
        func: Callable[..., Any],
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        """Initialize a function task.

        Args:
            func: The function to wrap.
            name: Task name (defaults to function name).
            description: Task description (defaults to function docstring).
        """
        self._func = func
        self._name = name or func.__name__
        self._description = description or func.__doc__ or "No description provided"

    @property
    def name(self) -> str:
        """Get the task name."""
        return self._name

    @property
    def description(self) -> str:
        """Get the task description."""
        return self._description

    async def execute(self, **kwargs: Any) -> Any:
        """Execute the wrapped function.

        Args:
            **kwargs: Arguments to pass to the function.

        Returns:
            The function result.
        """
        result = self._func(**kwargs)
        # Handle both sync and async functions
        if inspect.iscoroutine(result):
            return await result
        return result

    def get_parameters(self) -> list[TaskParameter]:
        """Get parameters from the wrapped function.

        Returns:
            List of TaskParameter objects.
        """
        sig = inspect.signature(self._func)
        hints = get_type_hints(self._func) if hasattr(self._func, "__annotations__") else {}
        params = []

        for param_name, param in sig.parameters.items():
            if param_name in ("self", "kwargs", "args"):
                continue

            param_type = hints.get(param_name, Any)
            type_name = getattr(param_type, "__name__", str(param_type))

            params.append(
                TaskParameter(
                    name=param_name,
                    type=type_name,
                    description=f"Parameter: {param_name}",
                    required=param.default == inspect.Parameter.empty,
                    default=None if param.default == inspect.Parameter.empty else param.default,
                )
            )

        return params
