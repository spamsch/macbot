"""macOS Keychain integration for secure API key storage.

Wraps the macOS `security` CLI to store and retrieve secrets
from the system Keychain. Falls back gracefully on non-macOS
platforms or when the `security` binary is unavailable.
"""

import logging
import subprocess

logger = logging.getLogger(__name__)

SERVICE_NAME = "son-of-simon"

# Maps provider names to Keychain account identifiers.
# Values are also the Settings field names for env-value lookups
# (e.g. settings.anthropic_api_key, settings.paperless_api_token).
ACCOUNT_MAP: dict[str, str] = {
    "anthropic": "anthropic_api_key",
    "openai": "openai_api_key",
    "openrouter": "openrouter_api_key",
    "gemini": "gemini_api_key",
    "paperless": "paperless_api_token",
    "telegram": "telegram_bot_token",
}

_TIMEOUT = 5  # seconds


def get_keychain(account: str) -> str | None:
    """Retrieve a secret from the macOS Keychain.

    Args:
        account: Account name (e.g. 'anthropic_api_key')

    Returns:
        The secret string, or None if not found / error.
    """
    try:
        result = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-a", account,
                "-s", SERVICE_NAME,
                "-w",
            ],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        # returncode 44 = item not found — expected, not an error
        if result.returncode != 44:
            logger.debug("Keychain lookup failed for %s: rc=%d", account, result.returncode)
        return None
    except FileNotFoundError:
        logger.debug("'security' binary not found — Keychain unavailable")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("Keychain lookup timed out for %s", account)
        return None
    except OSError as e:
        logger.debug("Keychain lookup error for %s: %s", account, e)
        return None


def set_keychain(account: str, secret: str) -> bool:
    """Store a secret in the macOS Keychain.

    Uses the -U flag to update if an entry already exists.

    Args:
        account: Account name (e.g. 'anthropic_api_key')
        secret: The secret value to store

    Returns:
        True on success, False on error.
    """
    try:
        result = subprocess.run(
            [
                "security",
                "add-generic-password",
                "-a", account,
                "-s", SERVICE_NAME,
                "-w", secret,
                "-U",
            ],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
        if result.returncode == 0:
            logger.info("Stored key in Keychain: %s", account)
            return True
        logger.warning("Failed to store in Keychain: %s (rc=%d)", account, result.returncode)
        return False
    except FileNotFoundError:
        logger.debug("'security' binary not found — Keychain unavailable")
        return False
    except subprocess.TimeoutExpired:
        logger.warning("Keychain store timed out for %s", account)
        return False
    except OSError as e:
        logger.debug("Keychain store error for %s: %s", account, e)
        return False


def delete_keychain(account: str) -> bool:
    """Remove a secret from the macOS Keychain.

    Args:
        account: Account name (e.g. 'anthropic_api_key')

    Returns:
        True on success, False on error or not found.
    """
    try:
        result = subprocess.run(
            [
                "security",
                "delete-generic-password",
                "-a", account,
                "-s", SERVICE_NAME,
            ],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
        if result.returncode == 0:
            logger.info("Deleted key from Keychain: %s", account)
            return True
        logger.debug("Keychain delete failed for %s: rc=%d", account, result.returncode)
        return False
    except FileNotFoundError:
        logger.debug("'security' binary not found — Keychain unavailable")
        return False
    except subprocess.TimeoutExpired:
        logger.warning("Keychain delete timed out for %s", account)
        return False
    except OSError as e:
        logger.debug("Keychain delete error for %s: %s", account, e)
        return False


def get_key_source(account: str, env_value: str) -> str:
    """Determine where an API key is coming from.

    Args:
        account: Account name (e.g. 'anthropic_api_key')
        env_value: The current value from the .env / Settings field

    Returns:
        'keychain', 'env', or 'none'
    """
    try:
        kc_value = get_keychain(account)
        if kc_value:
            return "keychain"
    except Exception:
        pass

    if env_value:
        return "env"

    return "none"
