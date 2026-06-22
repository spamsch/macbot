"""Low-level Telegram bot API wrapper.

Provides a simple async interface for sending and receiving messages
via the Telegram Bot API.
"""

import logging
from typing import Any

from telegram import Bot, Update
from telegram.error import TelegramError
from telegram.request import HTTPXRequest

logger = logging.getLogger(__name__)

# HTTP-level timeouts (seconds).  These are independent of the Telegram
# long-polling timeout and ensure that stale / half-open TCP connections
# (e.g. after macOS sleep/wake) fail fast instead of hanging.
_CONNECT_TIMEOUT = 10.0
_READ_TIMEOUT = 10.0
_WRITE_TIMEOUT = 10.0
_POOL_TIMEOUT = 5.0


# Telegram hard limit per message.
TELEGRAM_MAX_CHARS = 4096


def split_for_telegram(text: str, limit: int = TELEGRAM_MAX_CHARS) -> list[str]:
    """Split text into <=limit chunks on natural boundaries.

    Breaks on paragraph, then line, then sentence, then word boundaries (in that
    order of preference) so messages don't snap mid-word. A code fence (```) that
    would be split across chunks is closed at the end of one chunk and reopened
    at the start of the next, so formatting survives the split.

    Args:
        text: The full message text.
        limit: Maximum characters per chunk (Telegram's limit is 4096).

    Returns:
        A list of chunks, each <= limit characters.
    """
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text
    # Reserve room for fence-balancing markers we may add to a chunk.
    budget = limit - 8
    while len(remaining) > limit:
        window = remaining[:budget]
        split_at = budget
        for sep in ("\n\n", "\n", ". ", " "):
            idx = window.rfind(sep)
            if idx > budget * 0.5:  # avoid tiny chunks
                split_at = idx + len(sep)
                break
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)

    # Balance triple-backtick fences across chunk boundaries.
    open_fence = False
    for i, chunk in enumerate(chunks):
        if open_fence:
            chunk = "```\n" + chunk
        if chunk.count("```") % 2:
            chunk = chunk + "\n```"
            open_fence = True
        else:
            open_fence = False
        chunks[i] = chunk

    return chunks


def _make_bot(token: str) -> Bot:
    """Create a Bot instance with explicit HTTP timeouts."""
    request = HTTPXRequest(
        connect_timeout=_CONNECT_TIMEOUT,
        read_timeout=_READ_TIMEOUT,
        write_timeout=_WRITE_TIMEOUT,
        pool_timeout=_POOL_TIMEOUT,
    )
    return Bot(token=token, request=request)


class TelegramBot:
    """Simple Telegram bot wrapper using python-telegram-bot.

    This class provides low-level access to the Telegram Bot API
    for sending messages and receiving updates via long-polling.
    """

    def __init__(self, token: str):
        """Initialize the bot with a token.

        Args:
            token: Telegram bot token from @BotFather
        """
        self.token = token
        self._bot = _make_bot(token)

    async def get_me(self) -> dict[str, Any]:
        """Get information about the bot.

        Returns:
            Dictionary with bot info including id, username, first_name

        Raises:
            TelegramError: If the API call fails
        """
        user = await self._bot.get_me()
        return {
            "id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "is_bot": user.is_bot,
        }

    async def send_message(
        self,
        chat_id: str | int,
        text: str,
        parse_mode: str | None = "Markdown",
    ) -> bool:
        """Send a message to a chat.

        Args:
            chat_id: Telegram chat ID to send to
            text: Message text (max 4096 characters)
            parse_mode: Message parsing mode (Markdown, HTML, or None)

        Returns:
            True if message was sent successfully

        Raises:
            TelegramError: If the API call fails
        """
        # Telegram has a 4096 character limit
        if len(text) > TELEGRAM_MAX_CHARS:
            # Split on natural boundaries; send each chunk individually so a
            # markdown failure in one chunk doesn't lose the whole message.
            chunks = split_for_telegram(text)
            for chunk in chunks:
                try:
                    await self._bot.send_message(
                        chat_id=chat_id,
                        text=chunk,
                        parse_mode=parse_mode,
                    )
                except TelegramError:
                    # Chunk likely broke a markdown entity — retry plain
                    await self._bot.send_message(
                        chat_id=chat_id,
                        text=chunk,
                        parse_mode=None,
                    )
            return True

        await self._bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
        )
        return True

    async def edit_message(
        self,
        chat_id: str | int,
        message_id: int,
        text: str,
        parse_mode: str | None = "Markdown",
    ) -> bool:
        """Edit an existing message.

        Args:
            chat_id: Telegram chat ID
            message_id: ID of the message to edit
            text: New message text
            parse_mode: Message parsing mode

        Returns:
            True if message was edited successfully
        """
        try:
            await self._bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode=parse_mode,
            )
            return True
        except TelegramError as e:
            # "Message is not modified" is expected if text hasn't changed
            if "not modified" in str(e).lower():
                return True
            raise

    async def send_voice(
        self,
        chat_id: str | int,
        voice: bytes,
        caption: str | None = None,
    ) -> bool:
        """Send a voice message to a chat.

        Args:
            chat_id: Telegram chat ID to send to
            voice: OGG Opus audio bytes
            caption: Optional caption for the voice message

        Returns:
            True if voice message was sent successfully

        Raises:
            TelegramError: If the API call fails
        """
        await self._bot.send_voice(
            chat_id=chat_id,
            voice=voice,
            caption=caption,
        )
        return True

    async def get_updates(
        self,
        offset: int | None = None,
        timeout: int = 30,
    ) -> list[Update]:
        """Get new updates via long-polling.

        Args:
            offset: Identifier of the first update to be returned
            timeout: Timeout in seconds for long polling

        Returns:
            List of Update objects
        """
        updates = await self._bot.get_updates(
            offset=offset,
            timeout=timeout,
            allowed_updates=["message"],  # Includes text, voice, and other message types
        )
        return list(updates)

    async def refresh(self) -> None:
        """Shut down the current connection pool and create a fresh Bot.

        Call this after detecting a stale connection (e.g. after sleep/wake)
        to flush dead TCP sockets from the httpx pool.
        """
        try:
            await self._bot.shutdown()
        except Exception:
            pass  # best-effort; the old connection is dead anyway
        self._bot = _make_bot(self.token)
        logger.info("Telegram bot connection refreshed")

    async def close(self) -> None:
        """Close the bot connection."""
        await self._bot.shutdown()


async def validate_token(token: str) -> tuple[bool, str]:
    """Validate a Telegram bot token by calling getMe.

    Args:
        token: Telegram bot token to validate

    Returns:
        Tuple of (success, message) where message is either
        the bot username or an error description
    """
    if not token or ":" not in token:
        return False, "Invalid token format (expected 'ID:SECRET')"

    try:
        bot = TelegramBot(token)
        info = await bot.get_me()
        await bot.close()
        return True, f"@{info['username']}"
    except TelegramError as e:
        return False, f"API error: {e.message}"
    except Exception as e:
        return False, f"Connection error: {e}"
