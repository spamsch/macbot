# Tauri Chat Panel Plan

## Goals
- Add a full in-app chat panel for interacting with the `son` binary.
- Keep conversation history in memory for the app session so users can open/close the panel at will.
- Add a Doctor action that runs `son doctor` and shows its output in-app.

## Non-goals
- Persist chat history across app restarts.
- Replace the underlying `son` CLI protocols.
- Change how `son start` is launched (Terminal-based service launch is separate).

## Current State
- `serviceStore` starts `son start` by opening macOS Terminal via AppleScript (intentional for debug visibility) and stops via `pkill`.
- `runDoctor()` also opens Terminal.app.
- No in-app chat UI exists.
- Sidecar binary is bundled and shell plugin permissions already allow spawn/execute/kill/stdin (`capabilities/default.json` has `shell:allow-spawn`, `shell:allow-stdin-write`, `shell:allow-kill`).
- `son chat` currently uses Rich `console.input()` for prompts and `rich.markdown.Markdown` for output rendering — both require a TTY and produce ANSI escape codes over pipes.

## CLI Protocol: `son chat --stdio`

The existing `son chat` command is designed for interactive terminal use and cannot work reliably over a pipe. A new `--stdio` flag (or separate `son chat-api` subcommand) is needed.

### Requirements
- Read input from `sys.stdin.readline()` instead of Rich `console.input()`.
- Write output as plain text or structured JSON to `sys.stdout` instead of Rich Markdown.
- Use JSON-lines framing so the Tauri frontend can reliably parse messages.

### Protocol (JSON-lines over stdio)

```
→ stdin:  {"type": "message", "text": "check my calendar"}
← stdout: {"type": "chunk", "text": "Looking at your calendar..."}
← stdout: {"type": "chunk", "text": "You have 3 meetings today."}
← stdout: {"type": "done"}
← stdout: {"type": "error", "text": "API key not configured"}
```

Message types:
- `message` (stdin) — user sends a chat message.
- `chunk` (stdout) — streaming token/text from the assistant.
- `done` (stdout) — assistant finished responding, ready for next input.
- `error` (stdout) — non-fatal error to display in the UI.

This eliminates the need for ANSI rendering, xterm.js, and PTY plugins entirely.

## Proposed UX
- Add a "Chat" button on `Dashboard.svelte` that opens a right-side slide-in drawer (matching the existing pattern used by Skills, Memory, Heartbeat, and Settings panels).
- Chat panel contains:
  - Transcript area with streaming output.
  - Input box with Send and Stop buttons.
  - Status indicator for chat process (Connected, Disconnected, Error).
  - "Clear" button to reset transcript.
  - "Doctor" action that runs once and appends output as a system message.
- Closing the drawer hides UI only — the panel stays mounted to preserve scroll position, process state, and transcript.

## Process Model
- The chat panel manages its own process handle for `son chat --stdio`.
- The service (`son start`) continues to be managed via Terminal/AppleScript — this is a separate concern and remains unchanged.
- The two processes are independent: stopping the service does not affect chat, and vice versa.
- When the Tauri app window closes, spawned child processes are automatically killed by Tauri.

## Data Model
- `ChatMessage` struct in a Svelte store, stored in memory:
  - `id: string` — unique identifier.
  - `timestamp: number` — epoch ms.
  - `role: "user" | "assistant" | "system"` — message origin.
  - `text: string` — display text (accumulated from chunks for assistant messages).
  - `status: "streaming" | "complete" | "error"` — for assistant messages.
- Store keeps transcript across drawer open/close until app exit.

## Error Handling and Reconnection
- Detect process exit via Tauri child `close` event and exit code.
- On unexpected exit (non-zero code or crash):
  - Show an error status in the chat panel header.
  - Append a system message: "Chat process exited unexpectedly."
  - Show a "Reconnect" button that spawns a new `son chat --stdio` process.
- Reconnecting preserves the existing transcript but starts a fresh agent session (conversation history is not carried over to the new process).

## Doctor Command
- Add a `doctor()` method on the chat store (or keep on service store) that runs:
  - `son doctor --json` via `Command.sidecar()` with `execute()` (one-shot, not streaming).
- Append doctor output as a system message in the chat transcript.

## Implementation Steps

### Phase 1: CLI stdio mode (Python)
1. Add `--stdio` flag to `son chat` subcommand:
   - File: `src/macbot/cli.py`
   - When `--stdio`, use `sys.stdin.readline()` for input and JSON-lines for output.
   - Skip Rich prompts and Markdown rendering.
   - Flush stdout after each JSON line.
2. Test stdio mode manually:
   - `echo '{"type":"message","text":"hello"}' | son chat --stdio`

### Phase 2: Chat store (Svelte)
3. Add a new chat store:
   - File: `app/src/lib/stores/chat.svelte.ts`
   - Follow existing store pattern (`$state` runes, getter accessors, async methods).
   - Manage transcript array, process handle, and connection state.
   - `connect()` — spawn `son chat --stdio` sidecar, attach stdout/stderr/close listeners.
   - `send(text)` — write JSON-line to stdin.
   - `disconnect()` — kill child process.
   - Parse incoming JSON lines, accumulate chunks into current assistant message, finalize on `done`.

### Phase 3: Chat UI (Svelte)
4. Add chat panel component:
   - File: `app/src/lib/components/ChatPanel.svelte`
   - Right-side slide-in drawer matching existing panel pattern.
   - Auto-scroll to bottom on new messages.
   - Input box with Enter-to-send and Shift+Enter for newlines.
5. Wire into Dashboard:
   - File: `app/src/routes/Dashboard.svelte`
   - Add "Chat" toggle button alongside existing Skills/Memory/Heartbeat/Settings buttons.
   - Keep `ChatPanel` mounted (not conditionally rendered) to preserve state; toggle visibility.

### Phase 4: Doctor integration
6. Add Doctor action in chat panel:
   - Button in panel header or transcript area.
   - Runs `son doctor --json` via one-shot `execute()`.
   - Appends formatted output as a system message.

### Phase 5: Polish
7. Handle edge cases:
   - Process crash detection and reconnect button.
   - Disable Send button while assistant is streaming.
   - Scroll-to-bottom behavior (auto-scroll when at bottom, preserve position when scrolled up).
8. Verify permissions:
   - `capabilities/default.json` already allows sidecar spawn with args, stdin write, and kill — no changes expected.

## Test Plan
- `son chat --stdio` responds correctly to JSON-lines input from a pipe.
- `son chat --stdio` exits cleanly on stdin EOF.
- Open/close chat drawer and ensure transcript persists during session.
- Send messages and verify streaming chunks render incrementally.
- Kill the chat process externally and verify error state + reconnect button appear.
- Run Doctor and verify output appears as a system message.
- Service start/stop does not affect the chat process.
- Closing the Tauri app cleans up the chat child process.

## Risks and Mitigations
- **`son chat --stdio` may not handle all agent edge cases** (tool calls that prompt for confirmation, long-running tasks).
  - Mitigation: start with simple message/response flow; add confirmation protocol later if needed.
- **Multiple `son` processes may compete for shared resources** (e.g., lock files, API rate limits).
  - Mitigation: gate chat start if service is in a conflicting mode; document that chat and service share the same API keys.
- **Large transcripts may consume memory.**
  - Mitigation: cap transcript to a reasonable limit (e.g., 500 messages) and drop oldest messages.
