"""Tests for the task system."""

import pytest

from macbot.tasks import FunctionTask, Task, TaskRegistry


class SimpleTask(Task):
    """A simple test task."""

    @property
    def name(self) -> str:
        return "simple_task"

    @property
    def description(self) -> str:
        return "A simple task for testing"

    async def execute(self, value: str) -> str:
        return f"Processed: {value}"


class TestTask:
    """Tests for the Task base class."""

    def test_task_definition(self) -> None:
        """Test that task definitions are generated correctly."""
        task = SimpleTask()
        definition = task.to_definition()

        assert definition.name == "simple_task"
        assert definition.description == "A simple task for testing"
        assert len(definition.parameters) == 1
        assert definition.parameters[0].name == "value"

    def test_task_tool_schema(self) -> None:
        """Test that tool schemas are generated correctly."""
        task = SimpleTask()
        schema = task.to_tool_schema()

        assert schema["name"] == "simple_task"
        assert "input_schema" in schema
        assert "value" in schema["input_schema"]["properties"]

    @pytest.mark.asyncio
    async def test_task_execution(self) -> None:
        """Test that tasks can be executed."""
        task = SimpleTask()
        result = await task.execute(value="test")
        assert result == "Processed: test"


class TestFunctionTask:
    """Tests for FunctionTask."""

    def test_sync_function(self) -> None:
        """Test wrapping a sync function."""

        def add(a: int, b: int) -> int:
            """Add two numbers."""
            return a + b

        task = FunctionTask(add, name="add", description="Add two numbers")
        assert task.name == "add"
        assert task.description == "Add two numbers"

    @pytest.mark.asyncio
    async def test_sync_function_execution(self) -> None:
        """Test executing a wrapped sync function."""

        def multiply(x: int, y: int) -> int:
            return x * y

        task = FunctionTask(multiply)
        result = await task.execute(x=3, y=4)
        assert result == 12

    @pytest.mark.asyncio
    async def test_async_function_execution(self) -> None:
        """Test executing a wrapped async function."""

        async def async_echo(message: str) -> str:
            return f"Echo: {message}"

        task = FunctionTask(async_echo)
        result = await task.execute(message="hello")
        assert result == "Echo: hello"


class TestTaskRegistry:
    """Tests for TaskRegistry."""

    def test_register_task(self) -> None:
        """Test registering a task."""
        registry = TaskRegistry()
        task = SimpleTask()
        registry.register(task)

        assert registry.get("simple_task") is task

    def test_register_duplicate_fails(self) -> None:
        """Test that registering a duplicate task fails."""
        registry = TaskRegistry()
        registry.register(SimpleTask())

        with pytest.raises(ValueError, match="already registered"):
            registry.register(SimpleTask())

    def test_register_function(self) -> None:
        """Test registering a function as a task."""
        registry = TaskRegistry()

        def my_func(x: int) -> int:
            return x * 2

        registry.register_function(my_func, name="double")
        task = registry.get("double")

        assert task is not None
        assert task.name == "double"

    def test_task_decorator(self) -> None:
        """Test the @registry.task decorator."""
        registry = TaskRegistry()

        @registry.task(description="Triple a number")
        def triple(x: int) -> int:
            return x * 3

        task = registry.get("triple")
        assert task is not None
        assert task.description == "Triple a number"

    def test_list_tasks(self) -> None:
        """Test listing all tasks."""
        registry = TaskRegistry()
        registry.register(SimpleTask())

        @registry.task()
        def another_task() -> None:
            pass

        tasks = registry.list_tasks()
        assert len(tasks) == 2

    @pytest.mark.asyncio
    async def test_execute_task(self) -> None:
        """Test executing a task through the registry."""
        registry = TaskRegistry()
        registry.register(SimpleTask())

        result = await registry.execute("simple_task", value="test")
        assert result.success
        assert result.output == "Processed: test"

    @pytest.mark.asyncio
    async def test_execute_unknown_task(self) -> None:
        """Test executing an unknown task."""
        registry = TaskRegistry()
        result = await registry.execute("unknown_task")

        assert not result.success
        assert "not found" in (result.error or "")

    def test_get_tool_schemas(self) -> None:
        """Test getting tool schemas for all tasks."""
        registry = TaskRegistry()
        registry.register(SimpleTask())

        schemas = registry.get_tool_schemas()
        assert len(schemas) == 1
        assert schemas[0]["name"] == "simple_task"
