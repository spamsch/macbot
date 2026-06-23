"""Tasks: Telegram Integration

Provides tasks for the agent to send messages via Telegram.
"""

import logging
import os
from typing import Any

from macbot.config import settings
from macbot.tasks.base import Task

logger = logging.getLogger(__name__)


class TelegramSendTask(Task):
    """Send a message via Telegram."""

    @property
    def name(self) -> str:
        return "telegram_send"

    @property
    def description(self) -> str:
        return (
            "Send a message to the user via Telegram. Use this to proactively "
            "notify the user about important information, task completion, or alerts. "
            "The chat ID is auto-detected — just call this tool without a chat_id "
            "and it will find the right recipient automatically."
        )

    async def execute(self, message: str, chat_id: str | None = None) -> dict[str, Any]:
        """Send a message via Telegram.

        Args:
            message: The message text to send
            chat_id: Optional chat ID (uses default if not provided)

        Returns:
            Dictionary with result status
        """
        from macbot.telegram import TelegramBot

        token = settings.telegram_bot_token
        if not token:
            return {
                "success": False,
                "error": "Telegram not configured (MACBOT_TELEGRAM_BOT_TOKEN not set)",
            }

        target_chat = chat_id or settings.telegram_chat_id

        # Auto-detect chat ID from pending Telegram messages if not configured
        if not target_chat:
            target_chat = await self._detect_chat_id(token)

        if not target_chat:
            return {
                "success": False,
                "error": (
                    "No chat_id available. Please send any message to your "
                    "Telegram bot first, then try again."
                ),
            }

        try:
            from macbot.telegram.bot import content_fingerprint

            logger.info(
                "[tg-trace] pid=%s telegram_send TOOL chat=%s %s",
                os.getpid(), target_chat, content_fingerprint(message),
            )
            bot = TelegramBot(token)
            await bot.send_message(target_chat, message)
            await bot.close()
            return {
                "success": True,
                "message": "Message sent successfully",
                "chat_id": target_chat,
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to send message: {e}",
            }


    async def _detect_chat_id(self, token: str) -> str | None:
        """Try to detect chat ID from pending Telegram messages.

        Also persists the chat ID to ~/.macbot/.env and updates in-memory
        settings so subsequent calls don't need to re-detect.
        """
        from macbot.telegram import TelegramBot
        from pathlib import Path

        try:
            bot = TelegramBot(token)
            updates = await bot.get_updates(offset=None, timeout=0)
            await bot.close()

            for update in updates:
                if update.message:
                    chat_id = str(update.message.chat_id)

                    # Persist to config
                    env_file = Path.home() / ".macbot" / ".env"
                    if env_file.exists():
                        content = env_file.read_text()
                    else:
                        content = ""

                    lines = [l for l in content.splitlines()
                             if not l.strip().startswith("MACBOT_TELEGRAM_CHAT_ID=")]
                    lines.append(f"MACBOT_TELEGRAM_CHAT_ID={chat_id}")
                    env_file.write_text("\n".join(lines) + "\n")

                    # Update in-memory
                    settings.telegram_chat_id = chat_id
                    return chat_id
        except Exception:
            pass
        return None


def register_telegram_tasks(registry) -> None:
    """Register Telegram tasks with a registry.

    Args:
        registry: TaskRegistry to register tasks with.
    """
    registry.register(TelegramSendTask())
