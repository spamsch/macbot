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

import sys
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.output.vt100 import Vt100_Output


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
        multiline=True,
        key_bindings=kb,
        prompt_continuation="  ... ",
    )
    if history_file is not None:
        history_file.parent.mkdir(parents=True, exist_ok=True)
        kwargs["history"] = FileHistory(str(history_file))

    session = PromptSession(**kwargs)

    # Disable Cursor Position Report queries.  prompt_toolkit sends \033[6n
    # to ask the terminal where the cursor is; the terminal replies with
    # \033[row;colR.  When switching tabs the reply can arrive at the wrong
    # time, leaking as visible text (e.g. "^[[72;35R") and causing partial
    # re-renders of the prompt.
    output = session.output
    if isinstance(output, Vt100_Output):
        output.enable_cpr = False

    return session


async def async_prompt(session: PromptSession, prompt: str = "") -> str:
    """Prompt the user asynchronously and return stripped input.

    Uses ``erase_when_done=True`` so prompt_toolkit clears its own rendering
    on submit, then manually echoes the prompt + input once.  This avoids
    double-echo caused by Rich Console output corrupting prompt_toolkit's
    internal screen-position tracking between prompts.

    Args:
        session: A ``PromptSession`` created by :func:`create_input_session`.
        prompt: An ANSI-formatted prompt string.

    Returns:
        The user's input with leading/trailing whitespace removed.
    """
    def _pre_run() -> None:
        # Set erase_when_done on the underlying Application so prompt_toolkit
        # clears its own rendering on submit.  This avoids double-echo caused
        # by Rich Console output corrupting prompt_toolkit's screen tracking.
        session.app.erase_when_done = True

    result = await session.prompt_async(ANSI(prompt), pre_run=_pre_run)
    # prompt_toolkit erased its rendering — manually echo prompt + input once.
    sys.stdout.write(f"{prompt}{result}\n")
    sys.stdout.flush()
    return result.strip()
