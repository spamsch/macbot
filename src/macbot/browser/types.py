"""Type definitions for browser automation."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ElementRef:
    """Information about an element identified by a ref.

    Attributes:
        ref: The reference ID (e.g., "e1", "e2")
        role: ARIA role (e.g., "button", "link", "textbox")
        name: Accessible name (label, text content)
        value: Current value (for inputs)
        tag: HTML tag name
        interactive: Whether the element is interactive
    """

    ref: str
    role: str
    name: str | None = None
    value: str | None = None
    tag: str | None = None
    interactive: bool = True


@dataclass
class Snapshot:
    """A snapshot of the current page's interactive elements.

    Attributes:
        text: Human-readable snapshot text showing all elements with refs
        refs: Mapping of ref IDs to ElementRef objects
        url: Current page URL
        title: Page title
        timestamp: When the snapshot was taken
        stats: Statistics about the snapshot
    """

    text: str
    refs: dict[str, ElementRef] = field(default_factory=dict)
    url: str = ""
    title: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    stats: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Snapshot":
        """Create a Snapshot from JSON response."""
        refs = {}
        for ref_id, ref_data in data.get("refs", {}).items():
            refs[ref_id] = ElementRef(
                ref=ref_id,
                role=ref_data.get("role", "element"),
                name=ref_data.get("name"),
                value=ref_data.get("value"),
                tag=ref_data.get("tag"),
                interactive=ref_data.get("interactive", True),
            )

        return cls(
            text=data.get("snapshot", ""),
            refs=refs,
            url=data.get("url", ""),
            title=data.get("title", ""),
            timestamp=datetime.fromisoformat(data["timestamp"])
            if "timestamp" in data
            else datetime.now(),
            stats=data.get("stats", {}),
        )


@dataclass
class BrowserResult:
    """Result from a browser operation.

    Attributes:
        success: Whether the operation succeeded
        error: Error message if failed
        data: Additional data from the operation
    """

    success: bool
    error: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "BrowserResult":
        """Create a BrowserResult from JSON response."""
        return cls(
            success=data.get("success", False),
            error=data.get("error"),
            data={k: v for k, v in data.items() if k not in ("success", "error")},
        )
