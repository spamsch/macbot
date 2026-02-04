"""Tasks: Browser Automation

Provides agent tools for ARIA-based browser automation in Safari.
Uses semantic element references (e1, e2, etc.) instead of fragile CSS selectors.

Workflow:
    1. browser_navigate to a URL (injects ARIA library)
    2. browser_snapshot to see interactive elements with refs
    3. browser_click, browser_type, browser_select using refs
    4. browser_snapshot again after UI changes

Visual workflow (hybrid approach):
    1. browser_navigate to a URL
    2. browser_visual_snapshot to get screenshot with ref labels overlaid
    3. analyze_screenshot to have vision AI interpret the screenshot
    4. Use the refs identified by AI to interact

Example:
    # Navigate to a page
    await execute("browser_navigate", url="https://booking.com")

    # See what's on the page
    snap = await execute("browser_snapshot")
    # Shows: [e1] textbox "Destination", [e2] button "Search", etc.

    # Interact using refs
    await execute("browser_type", ref="e1", text="Paris")
    await execute("browser_click", ref="e2")
"""

import base64
import os
from typing import Any

from macbot.browser import SafariBrowser
from macbot.tasks.base import Task

# Shared browser instance for session continuity
_browser: SafariBrowser | None = None


def _get_browser() -> SafariBrowser:
    """Get or create the shared browser instance."""
    global _browser
    if _browser is None:
        _browser = SafariBrowser()
    return _browser


# =============================================================================
# NAVIGATION
# =============================================================================


class BrowserNavigateTask(Task):
    """Navigate Safari to a URL and prepare for ARIA-based automation."""

    @property
    def name(self) -> str:
        return "browser_navigate"

    @property
    def description(self) -> str:
        return (
            "Navigate Safari to a URL. This injects the ARIA library for element interaction. "
            "After navigation, use browser_snapshot to see interactive elements."
        )

    async def execute(
        self, url: str, new_tab: bool = False, timeout: int = 20
    ) -> dict[str, Any]:
        """Navigate to a URL.

        Args:
            url: The URL to navigate to.
            new_tab: Open in a new tab instead of current tab.
            timeout: Page load timeout in seconds.

        Returns:
            Dictionary with success status, url, and title.
        """
        browser = _get_browser()
        try:
            result = await browser.navigate(url, new_tab=new_tab, timeout=timeout)
            return {
                "success": result.success,
                "url": result.data.get("url", url),
                "title": result.data.get("title", ""),
                "message": f"Navigated to {url}. Use browser_snapshot to see interactive elements.",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


# =============================================================================
# SNAPSHOT
# =============================================================================


class BrowserSnapshotTask(Task):
    """Get an ARIA snapshot showing all interactive elements with refs."""

    @property
    def name(self) -> str:
        return "browser_snapshot"

    @property
    def description(self) -> str:
        return (
            "Get a snapshot of the current page showing all interactive elements with refs. "
            "Each element has a ref like 'e1', 'e2' that can be used with browser_click, "
            "browser_type, etc. Shows element roles (button, textbox, link) and labels."
        )

    async def execute(
        self, interactive_only: bool = True, max_elements: int = 200, inject: bool = False
    ) -> dict[str, Any]:
        """Get ARIA snapshot.

        Args:
            interactive_only: Only show interactive elements (default: True).
            max_elements: Maximum number of elements to include.
            inject: Re-inject the ARIA library (use if page changed without navigate).

        Returns:
            Dictionary with snapshot text showing elements and their refs.
        """
        browser = _get_browser()
        try:
            snapshot = await browser.snapshot(
                interactive_only=interactive_only,
                max_elements=max_elements,
                inject=inject,
            )
            return {
                "success": True,
                "snapshot": snapshot.text,
                "url": snapshot.url,
                "title": snapshot.title,
                "element_count": len(snapshot.refs),
                "stats": snapshot.stats,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


# =============================================================================
# INTERACTIONS
# =============================================================================


class BrowserClickTask(Task):
    """Click an element by its ref from the snapshot."""

    @property
    def name(self) -> str:
        return "browser_click"

    @property
    def description(self) -> str:
        return (
            "Click an element by its ref (e.g., 'e1', 'e5'). "
            "Get refs from browser_snapshot. The element is scrolled into view before clicking."
        )

    async def execute(self, ref: str) -> dict[str, Any]:
        """Click an element.

        Args:
            ref: Element reference from snapshot (e.g., "e1").

        Returns:
            Dictionary with success status.
        """
        browser = _get_browser()
        try:
            result = await browser.click(ref)
            if result.success:
                return {
                    "success": True,
                    "message": f"Clicked element {ref}. Use browser_snapshot to see the updated page.",
                }
            else:
                return {"success": False, "error": result.error or "Click failed"}
        except Exception as e:
            return {"success": False, "error": str(e)}


class BrowserTypeTask(Task):
    """Type text into an input element."""

    @property
    def name(self) -> str:
        return "browser_type"

    @property
    def description(self) -> str:
        return (
            "Type text into an input element identified by ref. "
            "By default clears the field first. Can optionally submit the form."
        )

    async def execute(
        self, ref: str, text: str, clear: bool = True, submit: bool = False
    ) -> dict[str, Any]:
        """Type into an element.

        Args:
            ref: Element reference from snapshot (e.g., "e1").
            text: Text to type.
            clear: Clear the field before typing (default: True).
            submit: Press Enter after typing to submit form (default: False).

        Returns:
            Dictionary with success status.
        """
        browser = _get_browser()
        try:
            result = await browser.type(ref, text, clear=clear, submit=submit)
            if result.success:
                msg = f"Typed '{text}' into element {ref}"
                if submit:
                    msg += " and submitted"
                return {"success": True, "message": msg}
            else:
                return {"success": False, "error": result.error or "Type failed"}
        except Exception as e:
            return {"success": False, "error": str(e)}


class BrowserSelectTask(Task):
    """Select an option in a dropdown element."""

    @property
    def name(self) -> str:
        return "browser_select"

    @property
    def description(self) -> str:
        return "Select an option in a dropdown/select element identified by ref."

    async def execute(self, ref: str, value: str) -> dict[str, Any]:
        """Select an option.

        Args:
            ref: Element reference for the select element.
            value: Option value or text to select.

        Returns:
            Dictionary with success status.
        """
        browser = _get_browser()
        try:
            result = await browser.select(ref, value)
            if result.success:
                return {
                    "success": True,
                    "message": f"Selected '{value}' in element {ref}",
                }
            else:
                return {"success": False, "error": result.error or "Select failed"}
        except Exception as e:
            return {"success": False, "error": str(e)}


class BrowserScrollToTask(Task):
    """Scroll an element into view."""

    @property
    def name(self) -> str:
        return "browser_scroll_to"

    @property
    def description(self) -> str:
        return "Scroll to make an element visible. Useful for elements outside the viewport."

    async def execute(self, ref: str) -> dict[str, Any]:
        """Scroll to element.

        Args:
            ref: Element reference to scroll to.

        Returns:
            Dictionary with success status.
        """
        browser = _get_browser()
        try:
            result = await browser.scroll_to(ref)
            if result.success:
                return {"success": True, "message": f"Scrolled to element {ref}"}
            else:
                return {"success": False, "error": result.error or "Scroll failed"}
        except Exception as e:
            return {"success": False, "error": str(e)}


class BrowserGetTextTask(Task):
    """Get the text content of an element."""

    @property
    def name(self) -> str:
        return "browser_get_text"

    @property
    def description(self) -> str:
        return "Get the text content of an element. Useful for reading values or content."

    async def execute(self, ref: str) -> dict[str, Any]:
        """Get element text.

        Args:
            ref: Element reference.

        Returns:
            Dictionary with the element's text content.
        """
        browser = _get_browser()
        try:
            text = await browser.get_text(ref)
            return {"success": True, "text": text}
        except Exception as e:
            return {"success": False, "error": str(e)}


class BrowserExecuteJsTask(Task):
    """Execute JavaScript code in the current Safari tab."""

    @property
    def name(self) -> str:
        return "browser_execute_js"

    @property
    def description(self) -> str:
        return (
            "Execute JavaScript code in Safari and return the result. "
            "Useful for extracting data from web pages that isn't visible in snapshots. "
            "The JavaScript should return a string or use JSON.stringify() for complex data."
        )

    async def execute(self, code: str) -> dict[str, Any]:
        """Execute JavaScript.

        Args:
            code: JavaScript code to execute. Use JSON.stringify() for complex results.

        Returns:
            Dictionary with 'success' and 'result' keys.

        Example:
            # Get page title
            browser_execute_js(code="document.title")

            # Extract data from elements
            browser_execute_js(code='''
                JSON.stringify(
                    Array.from(document.querySelectorAll('.price'))
                        .map(el => el.textContent)
                )
            ''')
        """
        browser = _get_browser()
        try:
            result = await browser.execute_js(code)
            return result
        except Exception as e:
            return {"success": False, "error": str(e)}


# =============================================================================
# UTILITIES
# =============================================================================


class BrowserScreenshotTask(Task):
    """Take a screenshot of the current page."""

    @property
    def name(self) -> str:
        return "browser_screenshot"

    @property
    def description(self) -> str:
        return "Take a screenshot of the current Safari page and save to a file."

    async def execute(self, output_path: str) -> dict[str, Any]:
        """Take a screenshot.

        Args:
            output_path: Path to save the screenshot.

        Returns:
            Dictionary with the saved file path.
        """
        browser = _get_browser()
        try:
            path = await browser.screenshot(output_path)
            return {"success": True, "path": str(path)}
        except Exception as e:
            return {"success": False, "error": str(e)}


class BrowserCloseTabTask(Task):
    """Close the current Safari tab."""

    @property
    def name(self) -> str:
        return "browser_close_tab"

    @property
    def description(self) -> str:
        return "Close the current Safari tab."

    async def execute(self) -> dict[str, Any]:
        """Close the current tab.

        Returns:
            Dictionary with success status.
        """
        browser = _get_browser()
        try:
            result = await browser.close()
            return {"success": result.success, "message": "Tab closed"}
        except Exception as e:
            return {"success": False, "error": str(e)}


class BrowserDismissCookiesTask(Task):
    """Dismiss cookie consent banners."""

    @property
    def name(self) -> str:
        return "browser_dismiss_cookies"

    @property
    def description(self) -> str:
        return (
            "Try to dismiss cookie consent banners on the current page. "
            "Useful when a consent popup blocks interaction with the page."
        )

    async def execute(self) -> dict[str, Any]:
        """Dismiss cookie consent.

        Returns:
            Dictionary with success status and whether a banner was dismissed.
        """
        browser = _get_browser()
        try:
            result = await browser.dismiss_cookies()
            return result
        except Exception as e:
            return {"success": False, "error": str(e)}


class BrowserWaitTask(Task):
    """Wait for page to stabilize after dynamic content loads."""

    @property
    def name(self) -> str:
        return "browser_wait"

    @property
    def description(self) -> str:
        return (
            "Wait for the page to stabilize (stop loading dynamic content). "
            "Use this after navigation or clicking if the page has animations or AJAX."
        )

    async def execute(self, seconds: float = 2.0) -> dict[str, Any]:
        """Wait for page stability.

        Args:
            seconds: How long to wait (default: 2 seconds).

        Returns:
            Dictionary with success status.
        """
        import asyncio
        await asyncio.sleep(seconds)
        return {"success": True, "message": f"Waited {seconds} seconds"}


class BrowserPressKeyTask(Task):
    """Press a keyboard key (Escape, Enter, Tab, etc.)."""

    @property
    def name(self) -> str:
        return "browser_press_key"

    @property
    def description(self) -> str:
        return (
            "Press a keyboard key. Use 'escape' to dismiss popups/overlays, "
            "'enter' to submit, 'tab' to move focus, or arrow keys for navigation. "
            "Supported: escape, enter, tab, space, backspace, arrowdown, arrowup, arrowleft, arrowright"
        )

    async def execute(self, key: str) -> dict[str, Any]:
        """Press a key.

        Args:
            key: Key to press (escape, enter, tab, etc.)

        Returns:
            Dictionary with success status.
        """
        browser = _get_browser()
        try:
            result = await browser.press_key(key)
            if result.success:
                return {"success": True, "message": f"Pressed {key}"}
            else:
                return {"success": False, "error": result.error or f"Failed to press {key}"}
        except Exception as e:
            return {"success": False, "error": str(e)}


class BrowserVisualSnapshotTask(Task):
    """Take a screenshot with ref labels overlaid on elements."""

    @property
    def name(self) -> str:
        return "browser_visual_snapshot"

    @property
    def description(self) -> str:
        return (
            "Take a screenshot with ref labels (e1, e2, etc.) visually overlaid on interactive elements. "
            "This combines visual understanding with precise refs - you can SEE what each element looks like "
            "and know its ref for clicking/typing. Returns the screenshot path."
        )

    async def execute(
        self, output_path: str = "/tmp/visual_snapshot.png", max_elements: int = 80
    ) -> dict[str, Any]:
        """Take visual snapshot with ref labels.

        Args:
            output_path: Where to save the screenshot.
            max_elements: Maximum number of elements to label.

        Returns:
            Dictionary with screenshot path and label count.
        """
        browser = _get_browser()
        try:
            result = await browser.visual_snapshot(output_path, max_elements)
            return result
        except Exception as e:
            return {"success": False, "error": str(e)}


class AnalyzeScreenshotTask(Task):
    """Use GPT-5.2 vision to analyze a screenshot with ref labels."""

    @property
    def name(self) -> str:
        return "analyze_screenshot"

    @property
    def description(self) -> str:
        return (
            "Analyze a screenshot using GPT-5.2 vision AI. The screenshot should have ref labels "
            "(e1, e2, etc.) overlaid on interactive elements (use browser_visual_snapshot first). "
            "Ask questions like 'Which ref is the search button?' or 'What refs should I click to select March 15?'"
        )

    async def execute(
        self,
        screenshot_path: str,
        question: str = "Describe what you see and list the important interactive elements with their refs.",
    ) -> dict[str, Any]:
        """Analyze screenshot with vision AI.

        Args:
            screenshot_path: Path to the screenshot file.
            question: What to ask about the screenshot.

        Returns:
            Dictionary with the AI's analysis.
        """
        try:
            from openai import AsyncOpenAI
            from macbot.config import settings

            # Read and encode image
            if not os.path.exists(screenshot_path):
                return {"success": False, "error": f"Screenshot not found: {screenshot_path}"}

            with open(screenshot_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode()

            # Determine image type
            if screenshot_path.endswith(".png"):
                media_type = "image/png"
            elif screenshot_path.endswith(".jpg") or screenshot_path.endswith(".jpeg"):
                media_type = "image/jpeg"
            else:
                media_type = "image/png"

            # Create OpenAI client
            client = AsyncOpenAI(api_key=settings.openai_api_key)

            # Get model - use configured model if OpenAI, otherwise default to gpt-4o
            vision_model = settings.model.split("/")[1] if settings.model.startswith("openai/") else "gpt-4o"

            # Send to vision model
            response = await client.chat.completions.create(
                model=vision_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are analyzing a screenshot of a web page that has red ref labels "
                            "(e1, e2, e3, etc.) overlaid on interactive elements. These labels indicate "
                            "which ref to use when clicking or typing. Be specific about which refs "
                            "correspond to which elements. Format your response clearly."
                        ),
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": question},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:{media_type};base64,{image_data}"},
                            },
                        ],
                    },
                ],
                max_completion_tokens=1000,
            )

            analysis = response.choices[0].message.content
            return {
                "success": True,
                "analysis": analysis,
                "screenshot": screenshot_path,
                "model": vision_model,
            }

        except ImportError:
            return {"success": False, "error": "OpenAI package not installed"}
        except Exception as e:
            return {"success": False, "error": str(e)}


# =============================================================================
# REGISTRATION
# =============================================================================


def register_browser_tasks(registry) -> None:
    """Register all browser automation tasks with a registry.

    Args:
        registry: TaskRegistry to register tasks with.
    """
    registry.register(BrowserNavigateTask())
    registry.register(BrowserSnapshotTask())
    registry.register(BrowserClickTask())
    registry.register(BrowserTypeTask())
    registry.register(BrowserSelectTask())
    registry.register(BrowserScrollToTask())
    registry.register(BrowserGetTextTask())
    registry.register(BrowserExecuteJsTask())
    registry.register(BrowserScreenshotTask())
    registry.register(BrowserCloseTabTask())
    registry.register(BrowserDismissCookiesTask())
    registry.register(BrowserWaitTask())
    registry.register(BrowserPressKeyTask())
    registry.register(BrowserVisualSnapshotTask())
    registry.register(AnalyzeScreenshotTask())
