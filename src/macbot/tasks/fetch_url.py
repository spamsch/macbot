"""Task: Fetch URL

Fetch content from a URL using HTTP requests.
"""

from typing import Any

import httpx

from macbot.tasks.base import Task
from macbot.tasks.registry import task_registry


class FetchURLTask(Task):
    """Fetch content from a URL.

    Makes HTTP requests using httpx with configurable method.
    Returns status code, headers, and body content.

    Example:
        task = FetchURLTask()
        result = await task.execute(url="https://example.com")
        # Returns: {"status_code": 200, "headers": {...}, "body": "..."}
    """

    @property
    def name(self) -> str:
        """Get the task name."""
        return "fetch_url"

    @property
    def description(self) -> str:
        """Get the task description."""
        return "Fetch content from a URL and return the response."

    async def execute(self, url: str, method: str = "GET") -> dict[str, Any]:
        """Fetch a URL.

        Args:
            url: The URL to fetch.
            method: HTTP method (GET, POST, etc.).

        Returns:
            Dictionary containing:
            - status_code: HTTP status code
            - headers: Response headers as dict
            - body: Response body (limited to 5000 chars)
        """
        async with httpx.AsyncClient() as client:
            response = await client.request(method, url)
            return {
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "body": response.text[:5000],  # Limit body size
            }


# Auto-register on import
task_registry.register(FetchURLTask())
