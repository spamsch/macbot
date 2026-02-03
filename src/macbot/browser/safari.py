"""Safari browser controller using ARIA-based automation."""

import asyncio
import json
import logging
import os
from typing import Any

from macbot.browser.types import BrowserResult, Snapshot

logger = logging.getLogger(__name__)

# Path to browser automation scripts
_PACKAGE_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
SCRIPTS_BASE = os.path.join(_PACKAGE_DIR, "macos-automation", "browser")


class BrowserError(Exception):
    """Exception raised for browser automation errors."""

    pass


async def _run_script(
    script_name: str, args: list[str] | None = None, timeout: int = 30
) -> dict[str, Any]:
    """Run a browser automation script.

    Args:
        script_name: Name of the script (e.g., "navigate.sh")
        args: Command line arguments
        timeout: Timeout in seconds

    Returns:
        Parsed JSON response from the script

    Raises:
        BrowserError: If script fails or returns error
    """
    script_path = os.path.join(SCRIPTS_BASE, script_name)

    if not os.path.exists(script_path):
        raise BrowserError(f"Script not found: {script_path}")

    cmd_parts = [script_path] + (args or [])
    cmd = " ".join(f'"{p}"' if " " in p else p for p in cmd_parts)

    logger.debug(f"Running browser script: {cmd}")

    try:
        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)

        stdout_str = stdout.decode().strip()
        stderr_str = stderr.decode().strip()

        logger.debug(f"Script stdout: {stdout_str[:500] if stdout_str else '(empty)'}")

        if stderr_str:
            logger.debug(f"Script stderr: {stderr_str}")

        if not stdout_str:
            raise BrowserError("Script returned no output")

        try:
            result = json.loads(stdout_str)
        except json.JSONDecodeError as e:
            raise BrowserError(f"Invalid JSON response: {e}\nOutput: {stdout_str[:200]}")

        if not result.get("success", True) and "error" in result:
            raise BrowserError(result["error"])

        return result

    except asyncio.TimeoutError:
        raise BrowserError(f"Script timed out after {timeout} seconds")
    except Exception as e:
        if isinstance(e, BrowserError):
            raise
        raise BrowserError(f"Script execution failed: {e}")


class SafariBrowser:
    """Safari browser controller with ARIA-based automation.

    This class provides methods to control Safari and interact with web pages
    using ARIA (Accessible Rich Internet Applications) roles instead of
    fragile CSS selectors.

    Workflow:
        1. navigate() to a URL (injects ARIA library)
        2. snapshot() to see interactive elements with refs
        3. click(), type(), select() using refs
        4. snapshot() again after UI changes

    Example:
        browser = SafariBrowser()
        await browser.navigate("https://google.com")
        snap = await browser.snapshot()
        # snap.text shows: [e1] textbox "Search", [e2] button "Google Search"
        await browser.type("e1", "python tutorials")
        await browser.click("e2")
    """

    def __init__(self):
        """Initialize the Safari browser controller."""
        self._last_snapshot: Snapshot | None = None

    async def navigate(
        self, url: str, new_tab: bool = False, timeout: int = 20
    ) -> BrowserResult:
        """Navigate to a URL in Safari.

        This also injects the ARIA snapshot library into the page.

        Args:
            url: The URL to navigate to
            new_tab: Open in a new tab instead of current tab
            timeout: Page load timeout in seconds

        Returns:
            BrowserResult with url and title

        Raises:
            BrowserError: If navigation fails
        """
        args = ["--timeout", str(timeout)]
        if new_tab:
            args.append("--new-tab")
        args.append(url)

        result = await _run_script("navigate.sh", args, timeout=timeout + 10)
        return BrowserResult.from_json(result)

    async def snapshot(
        self, interactive_only: bool = True, max_elements: int = 200, inject: bool = False
    ) -> Snapshot:
        """Get an ARIA snapshot of the current page.

        Returns a snapshot showing all interactive elements with refs that
        can be used for subsequent interactions.

        Args:
            interactive_only: Only include interactive elements (default: True)
            max_elements: Maximum number of elements to include
            inject: Re-inject the ARIA library before snapshot

        Returns:
            Snapshot object with text representation and refs mapping

        Raises:
            BrowserError: If snapshot fails
        """
        args = ["--max", str(max_elements)]
        if not interactive_only:
            args.append("--all")
        if inject:
            args.append("--inject")

        result = await _run_script("snapshot.sh", args)
        snapshot = Snapshot.from_json(result)
        self._last_snapshot = snapshot
        return snapshot

    async def click(self, ref: str) -> BrowserResult:
        """Click an element by its ref.

        Args:
            ref: Element reference from snapshot (e.g., "e1")

        Returns:
            BrowserResult

        Raises:
            BrowserError: If click fails (element not found, etc.)
        """
        result = await _run_script("click.sh", [ref])
        return BrowserResult.from_json(result)

    async def type(
        self, ref: str, text: str, clear: bool = True, submit: bool = False
    ) -> BrowserResult:
        """Type text into an input element.

        Args:
            ref: Element reference from snapshot
            text: Text to type
            clear: Clear the field first (default: True)
            submit: Press Enter after typing (default: False)

        Returns:
            BrowserResult

        Raises:
            BrowserError: If typing fails
        """
        args = []
        if not clear:
            args.append("--no-clear")
        if submit:
            args.append("--submit")
        args.extend([ref, text])

        result = await _run_script("type.sh", args)
        return BrowserResult.from_json(result)

    async def select(self, ref: str, value: str) -> BrowserResult:
        """Select an option in a dropdown.

        Args:
            ref: Element reference for the select element
            value: Option value or text to select

        Returns:
            BrowserResult

        Raises:
            BrowserError: If selection fails
        """
        result = await _run_script("select.sh", [ref, value])
        return BrowserResult.from_json(result)

    async def scroll_to(self, ref: str) -> BrowserResult:
        """Scroll an element into view.

        Args:
            ref: Element reference to scroll to

        Returns:
            BrowserResult
        """
        result = await _run_script("scroll.sh", [ref])
        return BrowserResult.from_json(result)

    async def get_text(self, ref: str) -> str:
        """Get the text content of an element.

        Args:
            ref: Element reference

        Returns:
            Text content of the element

        Raises:
            BrowserError: If element not found
        """
        result = await _run_script("get-text.sh", [ref])
        return result.get("text", "")

    async def screenshot(self, output_path: str | None = None) -> bytes | str:
        """Take a screenshot of the current page.

        Args:
            output_path: Optional path to save the screenshot

        Returns:
            If output_path: the path to the saved file
            Otherwise: screenshot data as bytes
        """
        args = []
        if output_path:
            args.extend(["--output", output_path])

        result = await _run_script("screenshot.sh", args, timeout=10)

        if output_path:
            return result.get("path", output_path)
        else:
            import base64

            return base64.b64decode(result.get("data", ""))

    async def close(self) -> BrowserResult:
        """Close the current Safari tab.

        Returns:
            BrowserResult
        """
        result = await _run_script("close-tab.sh", [])
        return BrowserResult.from_json(result)

    async def dismiss_cookies(self) -> dict:
        """Attempt to dismiss cookie consent banners.

        Returns:
            Dictionary with success status and whether a banner was dismissed.
        """
        result = await _run_script("dismiss-cookies.sh", [])
        return result

    async def press_key(self, key: str) -> BrowserResult:
        """Press a keyboard key.

        Args:
            key: Key to press (escape, enter, tab, space, backspace, arrow keys)

        Returns:
            BrowserResult
        """
        result = await _run_script("press-key.sh", [key])
        return BrowserResult.from_json(result)

    async def visual_snapshot(
        self, output_path: str = "/tmp/visual_snapshot.png", max_elements: int = 80
    ) -> dict[str, Any]:
        """Take a screenshot with ref labels overlaid on interactive elements.

        This combines visual context with element refs - the LLM can see what's
        on the page AND know which ref (e1, e2, etc.) corresponds to each element.

        Args:
            output_path: Where to save the screenshot
            max_elements: Maximum number of elements to label

        Returns:
            Dictionary with screenshot path and label count
        """
        args = ["--output", output_path, "--max", str(max_elements)]
        return await _run_script("visual-snapshot.sh", args, timeout=15)

    def get_last_snapshot(self) -> Snapshot | None:
        """Get the last snapshot taken.

        Returns:
            The last Snapshot or None if no snapshot has been taken
        """
        return self._last_snapshot

    def get_element_info(self, ref: str) -> dict[str, Any] | None:
        """Get info about an element from the last snapshot.

        Args:
            ref: Element reference

        Returns:
            Element info dict or None if not found
        """
        if not self._last_snapshot:
            return None
        elem = self._last_snapshot.refs.get(ref)
        if elem:
            return {
                "ref": elem.ref,
                "role": elem.role,
                "name": elem.name,
                "value": elem.value,
                "tag": elem.tag,
                "interactive": elem.interactive,
            }
        return None
