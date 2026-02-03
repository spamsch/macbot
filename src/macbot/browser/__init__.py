"""Safari Browser Automation Module.

This module provides ARIA-based browser automation for Safari using
AppleScript and JavaScript injection. It's inspired by OpenClaw's approach
but adapted for macOS/Safari.

Key concepts:
- Navigate to a page (injects ARIA library)
- Take a snapshot to see interactive elements with refs (e1, e2, etc.)
- Interact using refs (click, type, select)
- Take new snapshot after UI changes

Example:
    from macbot.browser import SafariBrowser

    browser = SafariBrowser()
    await browser.navigate("https://example.com")
    snapshot = await browser.snapshot()
    print(snapshot.text)  # Shows [e1] button "Submit", etc.
    await browser.click("e1")
"""

from macbot.browser.safari import SafariBrowser
from macbot.browser.types import Snapshot, ElementRef

__all__ = ["SafariBrowser", "Snapshot", "ElementRef"]
