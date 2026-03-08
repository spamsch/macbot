Based on my analysis of the changes, here are the release notes:

- **Dev mode sidecar** — In development mode, the Tauri app now uses `son` from the Python venv instead of requiring a bundled PyInstaller binary, simplifying local development.
- **Channel switching** — Added dropdown selector in chat panel to switch between channels (main, tasks, heartbeat, telegram, custom) with icon indicators and message counts.
- **Per-channel conversation state** — Each channel maintains its own conversation history and conversation ID; switching channels preserves and restores prior conversations automatically.
- **Model display in responses** — Chat messages now show which model was used in the response metadata alongside token count and cost.
- **Channel-aware routing** — Tool calls and responses are now filtered by channel, preventing cross-channel event pollution in the UI.
