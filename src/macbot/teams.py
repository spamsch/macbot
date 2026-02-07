"""Microsoft Teams integration via Microsoft Graph API.

Uses MSAL for OAuth authentication and httpx for API calls.
Supports multiple accounts stored under ~/.macbot/teams/<account_name>/.
"""

import json
from pathlib import Path
from typing import Any

import httpx
import msal

TEAMS_DIR = Path.home() / ".macbot" / "teams"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SCOPES = [
    "User.Read",
    "Team.ReadBasic.All",
    "Channel.ReadBasic.All",
    "ChannelMessage.Read.All",
    "ChannelMessage.Send",
    "Chat.Read",
    "Chat.ReadWrite",
    "ChatMessage.Read",
    "ChatMessage.Send",
]


class TeamsClient:
    """Client for Microsoft Graph Teams API with MSAL auth."""

    def __init__(self, account_name: str = "default") -> None:
        self.account_name = account_name
        self.account_dir = TEAMS_DIR / account_name
        self.config_path = self.account_dir / "config.json"
        self.cache_path = self.account_dir / "token_cache.json"

    def is_configured(self) -> bool:
        """Check if this account has been set up."""
        return self.config_path.exists()

    def load_config(self) -> dict[str, str]:
        """Load account config (client_id, tenant_id)."""
        if not self.config_path.exists():
            raise FileNotFoundError(
                f"Teams account '{self.account_name}' not configured. "
                f"Run teams_setup first."
            )
        return json.loads(self.config_path.read_text())

    def save_config(self, client_id: str, tenant_id: str) -> None:
        """Save account config."""
        self.account_dir.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps({"client_id": client_id, "tenant_id": tenant_id}, indent=2)
        )

    def _get_cache(self) -> msal.SerializableTokenCache:
        """Load or create MSAL token cache."""
        cache = msal.SerializableTokenCache()
        if self.cache_path.exists():
            cache.deserialize(self.cache_path.read_text())
        return cache

    def _save_cache(self, cache: msal.SerializableTokenCache) -> None:
        """Persist MSAL token cache to disk."""
        if cache.has_state_changed:
            self.account_dir.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(cache.serialize())

    def _get_app(self) -> tuple[msal.PublicClientApplication, msal.SerializableTokenCache]:
        """Create MSAL public client app with token cache."""
        config = self.load_config()
        cache = self._get_cache()
        app = msal.PublicClientApplication(
            client_id=config["client_id"],
            authority=f"https://login.microsoftonline.com/{config['tenant_id']}",
            token_cache=cache,
        )
        return app, cache

    def get_token_silent(self) -> str | None:
        """Try to acquire token silently from cache.

        Returns:
            Access token string, or None if silent acquisition fails.
        """
        app, cache = self._get_app()
        accounts = app.get_accounts()
        if not accounts:
            self._save_cache(cache)
            return None

        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        self._save_cache(cache)

        if result and "access_token" in result:
            return result["access_token"]
        return None

    def get_token_interactive(self) -> str:
        """Acquire token via interactive browser login.

        Returns:
            Access token string.

        Raises:
            RuntimeError: If authentication fails.
        """
        app, cache = self._get_app()
        result = app.acquire_token_interactive(scopes=SCOPES)
        self._save_cache(cache)

        if "access_token" in result:
            return result["access_token"]

        error = result.get("error_description", result.get("error", "Unknown error"))
        raise RuntimeError(f"Authentication failed: {error}")

    def get_token(self) -> str:
        """Get a valid access token, using cache first then interactive fallback.

        Returns:
            Access token string.
        """
        token = self.get_token_silent()
        if token:
            return token
        return self.get_token_interactive()

    async def graph_get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Make authenticated GET request to Graph API.

        Args:
            path: API path (e.g., "/me/joinedTeams")
            params: Optional query parameters

        Returns:
            Response JSON as dict.
        """
        token = self.get_token()
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{GRAPH_BASE}{path}",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            return response.json()

    async def graph_post(
        self, path: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        """Make authenticated POST request to Graph API.

        Args:
            path: API path
            body: Request body as dict

        Returns:
            Response JSON as dict.
        """
        token = self.get_token()
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{GRAPH_BASE}{path}",
                json=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            return response.json()


def list_accounts() -> list[str]:
    """List configured Teams account names."""
    if not TEAMS_DIR.exists():
        return []
    return [
        d.name
        for d in sorted(TEAMS_DIR.iterdir())
        if d.is_dir() and (d / "config.json").exists()
    ]


def get_default_account() -> str | None:
    """Return the single account name if only one exists, else None."""
    accounts = list_accounts()
    if len(accounts) == 1:
        return accounts[0]
    return None


def resolve_account(account_name: str | None) -> str:
    """Resolve account name: use given, auto-detect single, or raise error.

    Args:
        account_name: Explicit account name, or None for auto-detection.

    Returns:
        Resolved account name.

    Raises:
        ValueError: If no account configured or multiple accounts without explicit name.
    """
    if account_name:
        return account_name

    accounts = list_accounts()
    if not accounts:
        raise ValueError(
            "No Teams accounts configured. Run teams_setup first."
        )
    if len(accounts) == 1:
        return accounts[0]

    raise ValueError(
        f"Multiple Teams accounts configured: {', '.join(accounts)}. "
        f"Please specify account_name."
    )
