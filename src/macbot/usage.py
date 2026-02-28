"""Persistent usage tracking for LLM interactions.

Stores monthly token and cost data in a JSON file at ~/.macbot/usage.json
with file locking for concurrent access safety.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from filelock import FileLock

logger = logging.getLogger(__name__)

USAGE_FILE = Path.home() / ".macbot" / "usage.json"
STORAGE_VERSION = 1


class UsageTracker:
    """Tracks cumulative LLM usage and costs per month.

    Persists data to a JSON file so totals survive service restarts.
    Thread-safe via file locking.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or USAGE_FILE
        self._lock = FileLock(str(self._path.with_suffix(".lock")))

    def record(self, cost_data: dict[str, Any]) -> None:
        """Record a single interaction's usage.

        Args:
            cost_data: Dict from Agent.get_interaction_cost() with keys:
                input_tokens, output_tokens, total_tokens, cost, model.
        """
        if not cost_data.get("total_tokens"):
            return  # Nothing to record

        month_key = datetime.now(timezone.utc).strftime("%Y-%m")

        with self._lock:
            data = self._read()
            month = data["months"].setdefault(month_key, {
                "input_tokens": 0,
                "output_tokens": 0,
                "cost": 0.0,
                "interactions": 0,
            })
            month["input_tokens"] += cost_data.get("input_tokens", 0)
            month["output_tokens"] += cost_data.get("output_tokens", 0)
            if isinstance(cost_data.get("cost"), (int, float)):
                month["cost"] += cost_data["cost"]
            month["interactions"] += 1
            self._write(data)

    def get_monthly_summary(self) -> dict[str, Any]:
        """Get the current month's usage summary.

        Returns:
            Dict with input_tokens, output_tokens, cost, interactions
            for the current month. Returns zeroes if no data.
        """
        month_key = datetime.now(timezone.utc).strftime("%Y-%m")
        with self._lock:
            data = self._read()
        return data["months"].get(month_key, {
            "input_tokens": 0,
            "output_tokens": 0,
            "cost": 0.0,
            "interactions": 0,
        })

    def _read(self) -> dict[str, Any]:
        """Read storage file. Creates it if missing."""
        if not self._path.exists():
            return {"version": STORAGE_VERSION, "months": {}}
        try:
            content = self._path.read_text(encoding="utf-8")
            if not content.strip():
                return {"version": STORAGE_VERSION, "months": {}}
            return json.loads(content)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to read usage file, starting fresh: %s", e)
            return {"version": STORAGE_VERSION, "months": {}}

    def _write(self, data: dict[str, Any]) -> None:
        """Write storage file."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(data, indent=2),
            encoding="utf-8",
        )
