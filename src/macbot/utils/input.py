"""Readline-compatible multi-line input using prompt_toolkit.

Provides a shared PromptSession factory for ``son chat`` and ``son start``.

Key bindings:
  Enter       – submit input
  Alt+Enter   – insert newline  (Esc then Enter also works)
  Ctrl+D      – EOF / exit
  Up/Down     – history navigation
  Ctrl+R      – reverse history search

Multi-line paste is handled automatically via bracketed-paste mode.
"""

from __future__ import annotations

from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings


def create_input_session(history_file: Path | None = None) -> PromptSession:
    """Create a PromptSession with readline key bindings and multi-line support.

    Args:
        history_file: Optional path for persistent history.  When *None*,
            history is kept in memory only (current session).

    Returns:
        A configured ``PromptSession`` ready for interactive use.
    """
    kb = KeyBindings()

    @kb.add("enter", eager=True)
    def _submit(event):  # noqa: ANN001
        event.current_buffer.validate_and_handle()

    @kb.add("escape", "enter")
    def _newline(event):  # noqa: ANN001
        event.current_buffer.newline()

    kwargs: dict = dict(
        key_bindings=kb,
    )
    if history_file is not None:
        history_file.parent.mkdir(parents=True, exist_ok=True)
        kwargs["history"] = FileHistory(str(history_file))

    return PromptSession(**kwargs)


async def async_prompt(session: PromptSession, prompt: str = "") -> str:
    """Prompt the user asynchronously and return stripped input.

    Args:
        session: A ``PromptSession`` created by :func:`create_input_session`.
        prompt: An ANSI-formatted prompt string.

    Returns:
        The user's input with leading/trailing whitespace removed.
    """
    result = await session.prompt_async(ANSI(prompt))
    return result.strip()
