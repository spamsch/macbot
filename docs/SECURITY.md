# Security and Privacy

Son of Simon is designed to be secure by default. It does not store your passwords, does not require a local gateway, and keeps your data on your Mac.

## How it works

Your email, calendar, and other account credentials are managed by macOS Keychain — the same way Apple Mail and Calendar already handle them. The assistant talks to your apps through AppleScript. It never sees or stores your passwords.

Son of Simon does not require a separate local gateway service for normal use, and nothing needs to listen on a port just to access your Mail/Calendar/Notes data through the Apple apps.

## Security model

- **No stored passwords** — macOS Keychain handles authentication
- **No local gateway required** — fewer moving parts to configure and secure
- **No extra OAuth tokens for Apple apps** — the apps are already signed in, the agent just uses them
- **No browser automation for your own data** — AppleScript talks to apps directly
- **Clear data egress** — prompts go to your chosen LLM provider; optional Telegram sends messages via Telegram

## What data leaves my Mac?

- Prompts go to your chosen LLM provider (unless you use a local model via LiteLLM).
- If you enable Telegram, messages you send/receive go through Telegram.
- Son of Simon does not need to expose a local gateway server just to use Apple Mail/Calendar/Notes via AppleScript.

**Privacy note:** if you use a hosted LLM, the prompt you send (which may include email/calendar snippets) is transmitted to that provider. If you want to keep content local, use a local model via LiteLLM.

## What permissions does it need?

- **Automation** (required for AppleScript control of Mail/Calendar/Reminders/Notes/Safari)
- **Accessibility** (optional; required for certain browser automation flows)

If something fails, `son doctor` prints what's missing and points you at the right System Settings page.

## Where is memory stored?

- Primary file: `~/.macbot/memory.yaml`
- Reset by deleting or clearing that file (it will be recreated as needed)
- All data stays on your Mac under `~/.macbot/`
