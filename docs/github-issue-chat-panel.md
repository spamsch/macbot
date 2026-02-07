# Issue: Add In-App Chat Panel for `son`

## Summary
Add an in-app chat panel to the Tauri dashboard that allows interactive stdio chat with the `son` sidecar, retains session history while the panel is closed, and keeps existing service start/stop status working without launching macOS Terminal. Include a Doctor action that runs a separate shell command and appends results to the transcript. Add ANSI rendering support in the UI.

## Scope
- Replace Terminal-based service start/stop with direct sidecar spawn.
- Add a chat store + UI panel with session transcript.
- Add Doctor command integration.
- Add ANSI rendering support (xterm.js) and evaluate PTY plugin if required.

## Tasks
- Create `chat.svelte.ts` store to manage transcript and child process handle.
- Update `service.svelte.ts` to spawn `son start` via `Command.sidecar` and stop via `child.kill()`.
- Add chat panel UI to `Dashboard.svelte` with open/close toggle and input.
- Stream stdout/stderr into transcript and render in the panel.
- Add Doctor action that runs `son doctor` and appends output.
- Add ANSI renderer in the panel and pipe output into it.
- Verify capabilities allow spawn/stdin/kill for `binaries/son`.

## Acceptance Criteria
- User can open chat panel from dashboard, send messages, and see replies.
- Closing the panel does not lose transcript during the app session.
- Dashboard shows running state for `son start` and can stop it.
- Doctor action runs and shows output in the UI.
- ANSI output is rendered in the panel, or a documented fallback exists.

## Notes
- If `son chat` requires a TTY, add PTY plugin and attach to xterm.js.
- Avoid `pkill` to prevent killing chat or other `son` processes.
