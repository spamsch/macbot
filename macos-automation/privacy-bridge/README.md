# Letta Privacy Bridge

A small, installed macOS app that owns the privacy grants Letta skills depend on.

## Why an app and not `swift -e`

The old calendar scripts ran EventKit inside `swift -e`. That fails in three ways:

1. **No usage description.** TCC refuses to show a prompt when the requesting
   binary has no `NSCalendarsFullAccessUsageDescription`. A bare interpreter has
   none, so the request either dies silently or crashes the process.
2. **No stable identity.** TCC records a decision against a code signature or a
   bundle identifier. `swift`'s identity changes with every toolchain update, so
   an approval granted today is gone after the next Xcode update.
3. **Wrong attribution.** The grant lands on Terminal, iTerm, or whatever
   happened to spawn the interpreter — a much broader grant than intended, and
   one that disappears when the agent runs from a different host process.

The bridge fixes all three: one bundle ID (`ai.letta.privacybridge`), one set of
usage descriptions, one entry per pane in System Settings.

## Layout

```
macos-automation/privacy-bridge/
├── Sources/
│   ├── main.swift               # CLI dispatch, status, request, FDA, help
│   ├── AppHost.swift            # transparent LaunchServices relay for permission-bound commands
│   ├── Args.swift               # argument + date parsing
│   ├── Output.swift             # JSON stdout / stderr diagnostics contract
│   ├── Permissions.swift        # EventKit, Apple Events, FDA detection, Settings links
│   ├── CalendarCommands.swift   # calendar list / events / create
│   ├── ReminderCommands.swift   # reminders lists / list / create / complete
│   └── AutomationCommands.swift # Notes + Mail permission status, request, bounded probe
├── Resources/
│   ├── Info.plist               # bundle ID, LSUIElement, privacy usage strings
│   └── hardened.entitlements    # Developer-ID-only; apple-events, no sandbox
└── build-install.sh             # compile → bundle → sign → install
```

## Build and install

```bash
bash macos-automation/privacy-bridge/build-install.sh
```

No Xcode project and no GUI: the script drives `swiftc` directly, assembles the
bundle, signs it, installs to `~/Applications/Letta Privacy Bridge.app`, and
registers it with LaunchServices. Options: `--no-install`, `--dest <dir>`,
`--identity <name>`, `--no-snapshot`, `--request`.

The script also refreshes a source snapshot at
`~/Library/Application Support/LettaPrivacyBridge/src`, so the app can be rebuilt
from a machine that no longer has this repository:

```bash
bash ~/Library/Application\ Support/LettaPrivacyBridge/src/build-install.sh
```

### Signing

If `security find-identity` reports a `Developer ID Application` certificate (or
`LETTA_BRIDGE_SIGN_IDENTITY` / `--identity` is set), the script signs with it and
enables the hardened runtime plus `Resources/hardened.entitlements`. Otherwise it
signs ad-hoc (`codesign -s -`), which works fine for a local helper.

Consequence worth knowing: **ad-hoc signed apps are identified to TCC by their
code hash.** Rebuilding produces a new hash, so previously granted permissions
may need to be granted again. A Developer ID signature keeps a stable identity
across rebuilds. If you rebuild often without a Developer ID and prompts start
reappearing, that is why.

### Sandboxing

The app is deliberately **not** sandboxed. Under `com.apple.security.app-sandbox`
it would get a container, lose the ability to stat `~/Library/Mail` (which is how
Full Disk Access is detected), and need a temporary-exception entitlement for
every Apple Event target. All of that breaks the local-helper role, so the
entitlements file carries only `com.apple.security.automation.apple-events` and
that only when a Developer ID signature is in play.

## CLI

Every command prints exactly one JSON object on stdout. Diagnostics — and only
diagnostics — go to stderr. Exit code is `0` on `"ok": true`, `1` otherwise.
No command prints secrets, tokens, or credentials.

```bash
BRIDGE="$HOME/Applications/Letta Privacy Bridge.app/Contents/MacOS/letta-privacy-bridge"

"$BRIDGE" help
"$BRIDGE" status                       # every permission at once
"$BRIDGE" request all                  # visible, grantable system dialogs
"$BRIDGE" calendar list --with-counts
"$BRIDGE" calendar events --start 2026-07-21 --days 7
"$BRIDGE" calendar create --calendar Work --title "Review" --start "2026-07-22 15:00" --duration 45
"$BRIDGE" reminders lists
"$BRIDGE" reminders list --due-before 2026-07-25 --limit 25
"$BRIDGE" reminders create --title "Renew passport" --list Personal --due "2026-08-01 09:00"
"$BRIDGE" reminders complete --id <id>
"$BRIDGE" notes status                 # == automation status --app notes
"$BRIDGE" mail probe                   # counts only, never content
"$BRIDGE" fda status
"$BRIDGE" fda open-settings
"$BRIDGE" open-settings calendars|reminders|automation|full-disk-access|privacy
```

Error objects carry `code`, `message`, usually `hint`, and sometimes `recovery`
(a list of commands to run). Callers should branch on `error.code`, never on
message text.

## App hosting — one binary, correct attribution

Callers always run the same binary. There is no second entry point and no
"run it this way for permissions" mode.

Under the hood, TCC does not authorize a binary, it authorizes the process
*responsible* for the request. Run the executable straight from a shell and
launchd never launched an application: the terminal — or whatever agent spawned
it — stays responsible, so EventKit answers with the *caller's* Calendar grant.
That is how `request calendar` could report `authorized` while the very next
`calendar events` still saw `not_determined`. One binary, two TCC subjects.

So every command that reaches Calendar, Reminders, or Apple Events is
transparently hosted: the CLI relaunches the installed bundle through
LaunchServices with an internal marker and a private result path, the app
executes the command as its own responsible process, writes its JSON verdict,
and exits. The waiting CLI prints exactly that JSON and exits with the child's
status. Round trip is ~0.2s.

Hosted: `status`, `calendar …`, `reminders …`, `notes …`, `mail …`,
`automation …`, `request …`.
Direct: `help`, `version`, `fda status`, `fda open-settings`, `open-settings …`,
and the `<group> help` reference pages — none of them read a TCC-protected
resource.

Properties worth relying on:

- **One hop.** The child carries the marker and never relays again.
- **No focus theft.** Reads launch with `open -g` — no activation, no window,
  no Dock icon. Only request flows, which must present a dialog, come forward.
- **Same contract.** One JSON object on stdout, `0`/`1` exit, `error.code`
  unchanged. Diagnostics on stderr name the command, never the temporary path.
- **Argument safety.** Marker options arriving from outside are stripped before
  the child's argv is built, so a caller cannot inject a result path. Arguments
  carrying control characters, or exceeding 128 args / 8192 bytes each, are
  rejected with `invalid_argument`, `too_many_arguments`, or
  `argument_too_long` — before anything is launched.
- **Timeouts.** 120s by default for hosted commands, `--timeout` to change it;
  `host_timeout` if the app never answers.

If the binary is run from outside an app bundle, hosting is impossible. The
command still executes, and a stderr line says the result describes the calling
process rather than the bridge.

## How `request` works

`request [calendar|reminders|notes|mail|all]` does **not** ask in-process by
default. It uses the same relay as every other permission-bound command (see
*App hosting*), differing only in that its child must come to the foreground and
in how strictly its verdict is read. It relaunches the installed bundle through
LaunchServices (`open -n -a … --args request … --in-process --result-file <tmp>`), so macOS
treats the bridge — not the calling terminal or agent process — as the process
responsible for the prompt. The parent polls the result file (default 180s,
`--timeout`) and prints the child's JSON verbatim.

That indirection is the whole point. Calling `--in-process` from a terminal often
produces no dialog at all: TCC attributes the request to the responsible parent,
which may already hold a decision. Use `--in-process` only when the caller is
already a LaunchServices-launched app.

For Notes and Mail, `request` first launches the target hidden (`open -g -j`)
because `AEDeterminePermissionToAutomateTarget` cannot produce a decision for an
app that is not running.

## Full Disk Access — what is actually possible

macOS provides **no API to request or grant Full Disk Access**. There is no
prompt to trigger, no entitlement that grants it, and no way for an app to add
itself to the list. TCC accepts only a manual grant made by the user in System
Settings. Anything claiming otherwise is wrong.

What the bridge does instead:

- `fda status` detects the current state by opening FDA-protected paths
  (`~/Library/Application Support/com.apple.TCC/TCC.db`, `~/Library/Mail`,
  `~/Library/Safari`) and immediately closing them. No bytes are read, no
  content is reported — only a boolean per probe.
- `fda open-settings` opens
  `x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles`
  and returns `requires_manual_user_action: true` plus the exact click path.

Manual steps, in order:

1. System Settings > Privacy & Security > Full Disk Access.
2. Unlock if the list is dimmed.
3. `+`, then add `~/Applications/Letta Privacy Bridge.app` (or toggle it on).
4. Restart whatever process needs the access; TCC caches decisions per process.

## Data handling

- Calendar and Reminders data is returned only by commands that exist to return
  it (`calendar events`, `reminders list`). Nothing is cached or written to disk.
- The Notes and Mail integration is **status and bounded probes only**. The
  probes return counts — folders, notes, accounts, mailboxes, inbox unread total
  — and never titles, bodies, senders, subjects, or addresses. Content reads
  remain in the per-app automation scripts, which now run behind a grant that
  belongs to this app.
- The only file the app writes is the hosted-result handoff in `TMPDIR` — mode
  `0600`, deleted by the parent as soon as it is read (also on timeout). Its
  path is never printed.
- No network access. No telemetry.

## Known limitations

- Ad-hoc builds lose TCC grants on rebuild (see *Signing*).
- `automation status` reports `undetermined_app_not_running` (`-600`) when the
  target app is not running. That is macOS's answer, not a bug; run
  `automation request --app <app>` to get a real decision.
- The bridge builds for the host architecture only. Rebuild on the target Mac
  rather than copying the bundle between Intel and Apple Silicon machines.
- `request` blocks on a human answering a dialog. It is not usable in a fully
  headless run; it is the one step that genuinely needs the user.
