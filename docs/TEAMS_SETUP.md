# Microsoft Teams Setup

Son of Simon integrates with Microsoft Teams through the [Microsoft Graph API](https://learn.microsoft.com/en-us/graph/overview). This gives the agent access to your teams, channels, and chats — it can read messages, send replies, and list conversations.

## Why the Azure CLI?

Teams access requires an Azure AD app registration. Normally that means logging into the [Azure Portal](https://portal.azure.com), navigating through Azure Active Directory, creating an app, configuring redirect URIs, adding API permissions, and granting admin consent — a process that takes 10+ clicks across multiple pages and is easy to get wrong.

The [Azure CLI (`az`)](https://learn.microsoft.com/en-us/cli/azure/) handles all of this in a single command. Son of Simon's `teams_setup` task uses `az` under the hood to:

1. Log you in to your Microsoft tenant
2. Create the app registration with the correct permissions
3. Configure it as a public client (no client secret needed)
4. Store the credentials locally

You never need to open the Azure Portal. The `az` CLI does the heavy lifting, and the agent orchestrates the whole flow.

## Prerequisites

Install the Azure CLI:

```bash
brew install azure-cli
```

That's it. You need a Microsoft account with access to Teams (work/school or personal with a Teams license).

## Setup (the easy way)

Just ask the agent:

> "Set up Teams integration"

The agent will:
1. Check that `az` is installed
2. Open a browser window for you to sign in to your Microsoft account
3. Create an Azure AD app registration called `SonOfSimon-Teams-default`
4. Store the app's `client_id` and `tenant_id` under `~/.macbot/teams/default/config.json`
5. Open another browser window for MSAL authentication (this grants the app permission to act on your behalf)
6. Cache the access and refresh tokens at `~/.macbot/teams/default/token_cache.json`

After setup, tokens refresh automatically. You won't need to sign in again unless the refresh token expires (typically 90 days of inactivity).

## Setup (manual, if you prefer)

If you already have an Azure AD app or want to register one yourself:

1. Go to [Azure Portal > App registrations](https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade)
2. Click **New registration**
3. Name: `SonOfSimon-Teams` (or anything you like)
4. Supported account types: choose based on your tenant
5. Redirect URI: **Public client/native** with value `http://localhost`
6. After creation, note the **Application (client) ID** and **Directory (tenant) ID**
7. Go to **API permissions > Add a permission > Microsoft Graph > Delegated permissions** and add:
   - `User.Read`
   - `Team.ReadBasic.All`
   - `Channel.ReadBasic.All`
   - `ChannelMessage.Read.All`
   - `ChannelMessage.Send`
   - `Chat.Read`
   - `Chat.ReadWrite`
   - `ChatMessage.Read`
   - `ChatMessage.Send`

Then create the config file manually:

```bash
mkdir -p ~/.macbot/teams/default
cat > ~/.macbot/teams/default/config.json << 'EOF'
{
  "client_id": "YOUR_CLIENT_ID",
  "tenant_id": "YOUR_TENANT_ID"
}
EOF
```

Then ask the agent to log in:

> "Log in to Teams"

This will open a browser for MSAL authentication and cache the tokens.

## Multiple accounts

You can set up multiple Teams accounts — for example, a work tenant and a personal tenant:

> "Set up Teams integration with account name work"

> "Set up Teams integration with account name personal"

Each account gets its own directory:

```
~/.macbot/teams/
├── work/
│   ├── config.json
│   └── token_cache.json
└── personal/
    ├── config.json
    └── token_cache.json
```

When using Teams tasks, specify which account to use:

> "List my teams on the work account"

If you only have one account configured, it's used automatically — no need to specify.

Check all configured accounts:

> "Teams status"

## Permissions explained

All permissions are **delegated** (user-level, not application-level). The app acts on behalf of the signed-in user — it can only access what that user can access in Teams.

| Permission | What it allows |
|---|---|
| `User.Read` | Read your profile (required for sign-in) |
| `Team.ReadBasic.All` | List teams you've joined |
| `Channel.ReadBasic.All` | List channels in those teams |
| `ChannelMessage.Read.All` | Read channel messages |
| `ChannelMessage.Send` | Send messages to channels |
| `Chat.Read` | List your 1:1 and group chats |
| `Chat.ReadWrite` | Access chat metadata |
| `ChatMessage.Read` | Read chat messages |
| `ChatMessage.Send` | Send chat messages |

No admin consent is required for these delegated permissions in most tenants. If your organization restricts app registrations, ask your IT admin to approve the app.

## Token storage and security

- Tokens are stored locally at `~/.macbot/teams/<account>/token_cache.json`
- The cache contains access tokens (short-lived, ~1 hour) and refresh tokens (long-lived, ~90 days)
- No client secret is used — this is a public client (native app) flow
- Tokens never leave your machine (they're sent only to Microsoft's Graph API)
- To revoke access: delete the account directory or sign out from [myapps.microsoft.com](https://myapps.microsoft.com)

## Troubleshooting

**"az: command not found"** — Install with `brew install azure-cli`

**"az login failed"** — Make sure you're signing in with the correct Microsoft account. For work/school accounts, your tenant admin may need to allow Azure CLI sign-ins.

**"App registration failed"** — Your tenant may restrict who can create app registrations. Ask your IT admin, or use the manual setup above with an admin-created app.

**"Interactive auth failed"** — The MSAL browser window may have been closed too early. Run `teams_login` to retry.

**"Token expired"** — Refresh tokens last ~90 days. If you haven't used Teams in a while, run `teams_login` to re-authenticate.

**"Multiple accounts configured, specify account_name"** — You have more than one account. Add the account name to your request: "List my teams on the work account".

## Removing Teams integration

Delete the account directory:

```bash
rm -rf ~/.macbot/teams/default
```

Optionally remove the Azure AD app registration:

```bash
az ad app delete --id YOUR_CLIENT_ID
```
