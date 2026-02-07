"""Tasks: Microsoft Teams Integration

Provides tasks for the agent to set up, authenticate, and interact with
Microsoft Teams via the Microsoft Graph API. Supports multiple accounts.
"""

import asyncio
import json
import shutil
import subprocess
from typing import Any

from macbot.tasks.base import Task


def _check_configured(account_name: str | None) -> dict[str, Any] | str:
    """Resolve account or return error dict.

    Returns:
        Account name string on success, or error dict on failure.
    """
    from macbot.teams import resolve_account

    try:
        return resolve_account(account_name)
    except ValueError as e:
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Setup tasks
# ---------------------------------------------------------------------------


class TeamsSetupTask(Task):
    """Set up Microsoft Teams integration with Azure AD app registration."""

    @property
    def name(self) -> str:
        return "teams_setup"

    @property
    def description(self) -> str:
        return (
            "Set up Microsoft Teams integration. Requires the Azure CLI (az). "
            "Creates an Azure AD app registration with Teams permissions, "
            "stores the config, and performs initial browser-based login. "
            "Use account_name to support multiple accounts (default: 'default')."
        )

    async def execute(self, account_name: str = "default") -> dict[str, Any]:
        """Run full Teams setup flow.

        Args:
            account_name: Name for this account (e.g., 'work', 'personal')

        Returns:
            Dictionary with setup result
        """
        from macbot.teams import TeamsClient

        # 1. Check az CLI
        if not shutil.which("az"):
            return {
                "success": False,
                "error": (
                    "Azure CLI (az) not found. Install it with: brew install azure-cli"
                ),
            }

        # 2. az login
        try:
            proc = await asyncio.create_subprocess_exec(
                "az", "login", "--allow-no-subscriptions",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                return {
                    "success": False,
                    "error": f"az login failed: {stderr.decode().strip()}",
                }
        except Exception as e:
            return {"success": False, "error": f"az login failed: {e}"}

        # 3. Get tenant ID from logged-in account
        try:
            proc = await asyncio.create_subprocess_exec(
                "az", "account", "show", "--query", "tenantId", "-o", "tsv",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            tenant_id = stdout.decode().strip()
            if not tenant_id:
                return {
                    "success": False,
                    "error": "Could not determine tenant ID from az account.",
                }
        except Exception as e:
            return {"success": False, "error": f"Failed to get tenant: {e}"}

        # 4. Create Azure AD app registration
        app_name = f"SonOfSimon-Teams-{account_name}"
        permissions = (
            "Microsoft Graph/User.Read "
            "Microsoft Graph/Team.ReadBasic.All "
            "Microsoft Graph/Channel.ReadBasic.All "
            "Microsoft Graph/ChannelMessage.Read.All "
            "Microsoft Graph/ChannelMessage.Send "
            "Microsoft Graph/Chat.Read "
            "Microsoft Graph/Chat.ReadWrite "
            "Microsoft Graph/ChatMessage.Read "
            "Microsoft Graph/ChatMessage.Send"
        )

        try:
            # Create the app with required permissions
            create_cmd = [
                "az", "ad", "app", "create",
                "--display-name", app_name,
                "--public-client-redirect-uris", "http://localhost",
                "--required-resource-accesses", json.dumps([{
                    "resourceAppId": "00000003-0000-0000-c000-000000000000",
                    "resourceAccess": [
                        {"id": "e1fe6dd8-ba31-4d61-89e7-88639da4683d", "type": "Scope"},  # User.Read
                        {"id": "485be79e-c497-4b35-9400-0e3fa7f2a5d4", "type": "Scope"},  # Team.ReadBasic.All
                        {"id": "9d8982ae-4365-4f57-95e9-d6032a4c0b87", "type": "Scope"},  # Channel.ReadBasic.All
                        {"id": "767156cb-16ae-4d10-8f8b-41b657c8c8c8", "type": "Scope"},  # ChannelMessage.Read.All
                        {"id": "ebf0f66e-9fb1-49e4-a278-222f76911cf4", "type": "Scope"},  # ChannelMessage.Send
                        {"id": "b2e060da-3baf-4687-9611-f4ebc0f0cbde", "type": "Scope"},  # Chat.Read
                        {"id": "9ff7295e-131b-4d94-90e1-69fde507ac11", "type": "Scope"},  # Chat.ReadWrite
                        {"id": "cdcdac3a-fd45-410d-83ef-554db620e5c7", "type": "Scope"},  # ChatMessage.Read
                        {"id": "116b7235-7cc6-461e-b163-8e55691d839e", "type": "Scope"},  # ChatMessage.Send
                    ],
                }]),
                "--query", "appId",
                "-o", "tsv",
            ]
            proc = await asyncio.create_subprocess_exec(
                *create_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                return {
                    "success": False,
                    "error": f"App registration failed: {stderr.decode().strip()}",
                }
            client_id = stdout.decode().strip()
        except Exception as e:
            return {"success": False, "error": f"App registration failed: {e}"}

        # 5. Save config
        client = TeamsClient(account_name)
        client.save_config(client_id=client_id, tenant_id=tenant_id)

        # 6. Initial MSAL interactive login
        try:
            token = client.get_token_interactive()
            if not token:
                return {
                    "success": False,
                    "error": "Interactive authentication did not return a token.",
                }
        except Exception as e:
            return {
                "success": False,
                "error": f"Interactive auth failed: {e}. Config saved — retry with teams_login.",
            }

        return {
            "success": True,
            "account_name": account_name,
            "client_id": client_id,
            "tenant_id": tenant_id,
            "message": (
                f"Teams account '{account_name}' configured and authenticated. "
                f"You can now use Teams tasks."
            ),
        }


class TeamsLoginTask(Task):
    """Re-authenticate an existing Teams account."""

    @property
    def name(self) -> str:
        return "teams_login"

    @property
    def description(self) -> str:
        return (
            "Re-authenticate a Teams account via browser login. "
            "Use when the token has expired or you need to refresh credentials."
        )

    async def execute(self, account_name: str | None = None) -> dict[str, Any]:
        """Run interactive login for an account.

        Args:
            account_name: Account to log in (auto-detected if only one exists)

        Returns:
            Dictionary with login result
        """
        from macbot.teams import TeamsClient

        resolved = _check_configured(account_name)
        if isinstance(resolved, dict):
            return resolved

        client = TeamsClient(resolved)
        try:
            client.get_token_interactive()
            return {
                "success": True,
                "account_name": resolved,
                "message": f"Successfully authenticated Teams account '{resolved}'.",
            }
        except Exception as e:
            return {"success": False, "error": f"Login failed: {e}"}


class TeamsStatusTask(Task):
    """Check Teams integration status."""

    @property
    def name(self) -> str:
        return "teams_status"

    @property
    def description(self) -> str:
        return (
            "Check which Teams accounts are configured and whether tokens are valid. "
            "Shows account name, client_id, and token status for each."
        )

    async def execute(self) -> dict[str, Any]:
        """Check status of all configured accounts.

        Returns:
            Dictionary with account statuses
        """
        from macbot.teams import TeamsClient, list_accounts

        accounts = list_accounts()
        if not accounts:
            return {
                "success": True,
                "accounts": [],
                "message": "No Teams accounts configured. Run teams_setup to get started.",
            }

        statuses = []
        for name in accounts:
            client = TeamsClient(name)
            config = client.load_config()
            token = client.get_token_silent()
            statuses.append({
                "account_name": name,
                "client_id": config.get("client_id", ""),
                "tenant_id": config.get("tenant_id", ""),
                "token_valid": token is not None,
            })

        return {"success": True, "accounts": statuses}


# ---------------------------------------------------------------------------
# Usage tasks
# ---------------------------------------------------------------------------


class TeamsListTeamsTask(Task):
    """List joined Teams."""

    @property
    def name(self) -> str:
        return "teams_list_teams"

    @property
    def description(self) -> str:
        return "List all Microsoft Teams you have joined."

    async def execute(self, account_name: str | None = None) -> dict[str, Any]:
        """List joined teams.

        Args:
            account_name: Account to use (auto-detected if only one exists)

        Returns:
            Dictionary with teams list
        """
        from macbot.teams import TeamsClient

        resolved = _check_configured(account_name)
        if isinstance(resolved, dict):
            return resolved

        client = TeamsClient(resolved)
        try:
            data = await client.graph_get("/me/joinedTeams")
            teams = [
                {
                    "id": t.get("id"),
                    "name": t.get("displayName"),
                    "description": t.get("description"),
                }
                for t in data.get("value", [])
            ]
            return {"success": True, "teams": teams, "count": len(teams)}
        except Exception as e:
            return {"success": False, "error": f"Failed to list teams: {e}"}


class TeamsListChannelsTask(Task):
    """List channels in a team."""

    @property
    def name(self) -> str:
        return "teams_list_channels"

    @property
    def description(self) -> str:
        return "List channels in a Microsoft Teams team. Requires team_id from teams_list_teams."

    async def execute(
        self, team_id: str, account_name: str | None = None
    ) -> dict[str, Any]:
        """List channels for a team.

        Args:
            team_id: The team ID
            account_name: Account to use (auto-detected if only one exists)

        Returns:
            Dictionary with channels list
        """
        from macbot.teams import TeamsClient

        resolved = _check_configured(account_name)
        if isinstance(resolved, dict):
            return resolved

        client = TeamsClient(resolved)
        try:
            data = await client.graph_get(f"/teams/{team_id}/channels")
            channels = [
                {
                    "id": ch.get("id"),
                    "name": ch.get("displayName"),
                    "description": ch.get("description"),
                    "membership_type": ch.get("membershipType"),
                }
                for ch in data.get("value", [])
            ]
            return {"success": True, "channels": channels, "count": len(channels)}
        except Exception as e:
            return {"success": False, "error": f"Failed to list channels: {e}"}


class TeamsReadChannelMessagesTask(Task):
    """Read recent messages from a Teams channel."""

    @property
    def name(self) -> str:
        return "teams_read_channel_messages"

    @property
    def description(self) -> str:
        return (
            "Read recent messages from a Teams channel. "
            "Requires team_id and channel_id. Returns messages with sender, timestamp, and content."
        )

    async def execute(
        self,
        team_id: str,
        channel_id: str,
        limit: int = 20,
        account_name: str | None = None,
    ) -> dict[str, Any]:
        """Read channel messages.

        Args:
            team_id: The team ID
            channel_id: The channel ID
            limit: Maximum number of messages to return (default: 20)
            account_name: Account to use (auto-detected if only one exists)

        Returns:
            Dictionary with messages
        """
        from macbot.teams import TeamsClient

        resolved = _check_configured(account_name)
        if isinstance(resolved, dict):
            return resolved

        client = TeamsClient(resolved)
        try:
            data = await client.graph_get(
                f"/teams/{team_id}/channels/{channel_id}/messages",
                params={"$top": limit},
            )
            messages = []
            for msg in data.get("value", []):
                body = msg.get("body", {})
                sender = msg.get("from", {})
                user = sender.get("user", {}) if sender else {}
                messages.append({
                    "id": msg.get("id"),
                    "sender": user.get("displayName", "Unknown"),
                    "timestamp": msg.get("createdDateTime"),
                    "content": body.get("content", ""),
                    "content_type": body.get("contentType", "text"),
                })
            return {"success": True, "messages": messages, "count": len(messages)}
        except Exception as e:
            return {"success": False, "error": f"Failed to read messages: {e}"}


class TeamsSendChannelMessageTask(Task):
    """Send a message to a Teams channel."""

    @property
    def name(self) -> str:
        return "teams_send_channel_message"

    @property
    def description(self) -> str:
        return (
            "Send a message to a Microsoft Teams channel. "
            "Requires team_id, channel_id, and the message text."
        )

    async def execute(
        self,
        team_id: str,
        channel_id: str,
        message: str,
        account_name: str | None = None,
    ) -> dict[str, Any]:
        """Send a channel message.

        Args:
            team_id: The team ID
            channel_id: The channel ID
            message: Message text to send
            account_name: Account to use (auto-detected if only one exists)

        Returns:
            Dictionary with send result
        """
        from macbot.teams import TeamsClient

        resolved = _check_configured(account_name)
        if isinstance(resolved, dict):
            return resolved

        client = TeamsClient(resolved)
        try:
            result = await client.graph_post(
                f"/teams/{team_id}/channels/{channel_id}/messages",
                body={"body": {"content": message}},
            )
            return {
                "success": True,
                "message_id": result.get("id"),
                "message": "Message sent successfully.",
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to send message: {e}"}


class TeamsListChatsTask(Task):
    """List recent chats."""

    @property
    def name(self) -> str:
        return "teams_list_chats"

    @property
    def description(self) -> str:
        return (
            "List recent Microsoft Teams chats (1:1, group, and meeting chats). "
            "Returns chat type, topic, and last updated time."
        )

    async def execute(
        self, limit: int = 20, account_name: str | None = None
    ) -> dict[str, Any]:
        """List recent chats.

        Args:
            limit: Maximum number of chats to return (default: 20)
            account_name: Account to use (auto-detected if only one exists)

        Returns:
            Dictionary with chats list
        """
        from macbot.teams import TeamsClient

        resolved = _check_configured(account_name)
        if isinstance(resolved, dict):
            return resolved

        client = TeamsClient(resolved)
        try:
            data = await client.graph_get(
                "/me/chats",
                params={
                    "$top": limit,
                    "$orderby": "lastMessagePreview/createdDateTime desc",
                    "$expand": "members",
                },
            )
            chats = []
            for chat in data.get("value", []):
                members = []
                for m in chat.get("members", []):
                    display_name = m.get("displayName")
                    if display_name:
                        members.append(display_name)

                chats.append({
                    "id": chat.get("id"),
                    "topic": chat.get("topic"),
                    "chat_type": chat.get("chatType"),
                    "last_updated": chat.get("lastUpdatedDateTime"),
                    "members": members,
                })
            return {"success": True, "chats": chats, "count": len(chats)}
        except Exception as e:
            return {"success": False, "error": f"Failed to list chats: {e}"}


class TeamsReadChatMessagesTask(Task):
    """Read messages from a Teams chat."""

    @property
    def name(self) -> str:
        return "teams_read_chat_messages"

    @property
    def description(self) -> str:
        return (
            "Read recent messages from a Teams chat. "
            "Requires chat_id from teams_list_chats. Returns messages with sender and timestamp."
        )

    async def execute(
        self,
        chat_id: str,
        limit: int = 20,
        account_name: str | None = None,
    ) -> dict[str, Any]:
        """Read chat messages.

        Args:
            chat_id: The chat ID
            limit: Maximum number of messages to return (default: 20)
            account_name: Account to use (auto-detected if only one exists)

        Returns:
            Dictionary with messages
        """
        from macbot.teams import TeamsClient

        resolved = _check_configured(account_name)
        if isinstance(resolved, dict):
            return resolved

        client = TeamsClient(resolved)
        try:
            data = await client.graph_get(
                f"/me/chats/{chat_id}/messages",
                params={"$top": limit},
            )
            messages = []
            for msg in data.get("value", []):
                body = msg.get("body", {})
                sender = msg.get("from", {})
                user = sender.get("user", {}) if sender else {}
                messages.append({
                    "id": msg.get("id"),
                    "sender": user.get("displayName", "Unknown"),
                    "timestamp": msg.get("createdDateTime"),
                    "content": body.get("content", ""),
                    "content_type": body.get("contentType", "text"),
                })
            return {"success": True, "messages": messages, "count": len(messages)}
        except Exception as e:
            return {"success": False, "error": f"Failed to read messages: {e}"}


class TeamsSendChatMessageTask(Task):
    """Send a message in a Teams chat."""

    @property
    def name(self) -> str:
        return "teams_send_chat_message"

    @property
    def description(self) -> str:
        return (
            "Send a message in a Microsoft Teams chat. "
            "Requires chat_id from teams_list_chats and the message text."
        )

    async def execute(
        self,
        chat_id: str,
        message: str,
        account_name: str | None = None,
    ) -> dict[str, Any]:
        """Send a chat message.

        Args:
            chat_id: The chat ID
            message: Message text to send
            account_name: Account to use (auto-detected if only one exists)

        Returns:
            Dictionary with send result
        """
        from macbot.teams import TeamsClient

        resolved = _check_configured(account_name)
        if isinstance(resolved, dict):
            return resolved

        client = TeamsClient(resolved)
        try:
            result = await client.graph_post(
                f"/me/chats/{chat_id}/messages",
                body={"body": {"content": message}},
            )
            return {
                "success": True,
                "message_id": result.get("id"),
                "message": "Message sent successfully.",
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to send message: {e}"}


def register_teams_tasks(registry) -> None:  # type: ignore[no-untyped-def]
    """Register Teams tasks with a registry.

    Args:
        registry: TaskRegistry to register tasks with.
    """
    registry.register(TeamsSetupTask())
    registry.register(TeamsLoginTask())
    registry.register(TeamsStatusTask())
    registry.register(TeamsListTeamsTask())
    registry.register(TeamsListChannelsTask())
    registry.register(TeamsReadChannelMessagesTask())
    registry.register(TeamsSendChannelMessageTask())
    registry.register(TeamsListChatsTask())
    registry.register(TeamsReadChatMessagesTask())
    registry.register(TeamsSendChatMessageTask())
