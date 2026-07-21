// ==============================================================================
// main.swift - Letta Privacy Bridge CLI entry point.
// ==============================================================================
// A durable, installed macOS app that owns the TCC grants used by Letta skills.
// Every command prints one JSON object on stdout; diagnostics go to stderr.
// ==============================================================================

import EventKit
import Foundation

// LaunchServices appends `-psn_0_…` on some launch paths. It is not ours and it
// would otherwise be parsed as a positional argument.
let arguments = Array(CommandLine.arguments.dropFirst()).filter { !$0.hasPrefix("-psn_") }
let parsed = Args(arguments)
let command = parsed.positional(0) ?? "help"

// Permission-bound commands cannot answer truthfully from a shell-launched
// process: TCC would report the *caller's* grants. Anything that touches
// Calendar, Reminders, or Apple Events is transparently relaunched inside the
// installed app and its JSON relayed back. Non-sensitive commands (help,
// version, fda, open-settings) stay direct. See AppHost.swift.
AppHost.interceptOrPrepare(command: command, arguments: arguments, args: parsed)

switch command {
case "help", "--help", "-h":
    Help.emit()

case "version", "--version", "-v":
    Out.success("version", [
        "version": bridgeVersion,
        "bundle_id": Bundle.main.bundleIdentifier ?? bridgeBundleID,
        "bundle_path": Bundle.main.bundleURL.path,
        "installed_as_app": Bundle.main.bundleIdentifier != nil,
    ])

case "status":
    StatusCommand.run()

case "request":
    RequestCommand.run(parsed)

case "calendar":
    CalendarCommands.run(parsed)

case "reminders":
    ReminderCommands.run(parsed)

case "automation", "notes", "mail":
    // `notes`/`mail` are shorthands for the permission verbs:
    //   `notes status` == `automation status --app notes`
    // Everything else under `notes` is a content operation handled in-process.
    if command == "automation" {
        AutomationCommands.run(parsed)
    } else {
        let sub = parsed.positional(1) ?? "status"
        if command == "notes", NotesCommands.subcommands.contains(sub) {
            NotesCommands.run(parsed)
        }
        AutomationCommands.run(Args(["automation", sub, "--app", command]
            + Array(arguments.dropFirst(2))))
    }

case "fda", "full-disk-access":
    FDACommand.run(parsed)

case "open-settings":
    let raw = parsed.positional(1) ?? parsed.string("pane") ?? "privacy"
    guard let pane = SettingsPane(rawValue: raw) else {
        Out.failure("open-settings", BridgeError(
            code: "unknown_pane",
            message: "Unknown pane \"\(raw)\"",
            hint: "Available: " + SettingsPane.allCases.map(\.rawValue).joined(separator: ", ")
        ))
    }
    let opened = pane.open()
    Out.success("open-settings", [
        "pane": pane.rawValue,
        "label": pane.label,
        "url": pane.url,
        "opened": opened,
    ])

default:
    Out.failure("unknown", BridgeError(
        code: "unknown_command",
        message: "Unknown command \"\(command)\"",
        hint: "Run `letta-privacy-bridge help` for the command reference."
    ))
}

// MARK: - status

enum StatusCommand {
    static func run() -> Never {
        let automation = AutomationTarget.all.map { entry -> [String: Any] in
            let result = AutomationPermissions.check(entry, askUser: false)
            return [
                "app": entry.key,
                "bundle_id": entry.bundleID,
                "status": result.status,
                "os_status": Int(result.osStatus),
            ]
        }

        Out.success("status", [
            "app": [
                "bundle_id": Bundle.main.bundleIdentifier ?? bridgeBundleID,
                "bundle_path": Bundle.main.bundleURL.path,
                "installed_as_app": Bundle.main.bundleIdentifier != nil,
                "version": bridgeVersion,
            ],
            "calendar": [
                "authorization": EventKitPermissions.statusName(for: .event),
                "full_access": EventKitPermissions.hasFullAccess(.event),
                "requestable": true,
            ],
            "reminders": [
                "authorization": EventKitPermissions.statusName(for: .reminder),
                "full_access": EventKitPermissions.hasFullAccess(.reminder),
                "requestable": true,
            ],
            "automation": ["targets": automation, "requestable": true],
            "full_disk_access": FullDiskAccess.status(),
        ])
    }
}

// MARK: - request

enum RequestCommand {
    static let allSubjects = ["calendar", "reminders", "notes", "mail"]

    static func run(_ args: Args) -> Never {
        let cmd = "request"
        var subjects = args.positionals.dropFirst().map { $0.lowercased() }
        if subjects.isEmpty || subjects.contains("all") { subjects = allSubjects }

        let unknown = subjects.filter { !allSubjects.contains($0) }
        guard unknown.isEmpty else {
            Out.failure(cmd, BridgeError(
                code: "unknown_subject",
                message: "Unknown permission subject(s): \(unknown.joined(separator: ", "))",
                hint: "Available: " + allSubjects.joined(separator: ", ") + ", all"
            ))
        }

        let timeout = TimeInterval(args.int("timeout") ?? 180)

        if args.bool("in-process") {
            // Becomes a foreground AppKit app and never returns; see RequestApp.swift.
            RequestApp.run(
                subjects: Array(subjects),
                resultFile: args.string("result-file"),
                timeout: max(30, timeout)
            )
        }
        relaunchThroughLaunchServices(Array(subjects), timeout: timeout)
    }

    /// Relaunches this app through LaunchServices so macOS treats the bridge —
    /// not the calling terminal — as the process responsible for the prompt.
    /// That is what makes the dialog visible and grantable to this app. Same
    /// hosting mechanism every permission-bound command uses (AppHost.swift);
    /// `request` differs only in that its child must come to the foreground and
    /// in how strictly the returned verdict is read.
    private static func relaunchThroughLaunchServices(_ subjects: [String], timeout: TimeInterval) -> Never {
        guard Bundle.main.bundleIdentifier != nil else {
            Out.failure("request", BridgeError(
                code: "not_installed_as_app",
                message: "This binary is not running from inside an app bundle",
                hint: "Install the app first, then run the copy inside " +
                      "~/Applications/Letta Privacy Bridge.app/Contents/MacOS/.",
                recovery: ["bash macos-automation/privacy-bridge/build-install.sh"]
            ))
        }

        // The child gives up slightly earlier so the parent reads a real result
        // file rather than timing out on its own with nothing to report.
        let childTimeout = Int(max(30, timeout - 10))
        let verdict = AppHost.launchAndAwait(
            childArguments: ["request"] + subjects
                + ["--in-process", "--timeout", String(childTimeout)],
            resultOption: "result-file",
            foreground: true,
            timeout: timeout,
            command: "request",
            timeoutError: BridgeError(
                code: "request_timeout",
                message: "No answer within \(Int(timeout))s",
                hint: "A system dialog is probably still open, or it was dismissed. " +
                      "Answer it and rerun, or grant access manually.",
                recovery: ["letta-privacy-bridge open-settings calendars",
                           "letta-privacy-bridge open-settings reminders",
                           "letta-privacy-bridge open-settings automation"]
            )
        )
        relay(verdict)
    }

    /// Prints the child's verdict verbatim — but never upgrades it. If any
    /// subject came back ungranted while its authorization is still
    /// `not_determined`, no dialog was ever presented, and that is a failure
    /// regardless of what the child wrote.
    private static func relay(_ object: [String: Any]) -> Never {
        let results = object["results"] as? [String: Any] ?? [:]
        let notPresented = RequestVerdict.notPresented(in: results)

        guard notPresented.isEmpty else {
            Out.failure("request", BridgeError(
                code: "authorization_not_presented",
                message: "No authorization dialog was presented for " +
                         "\(notPresented.joined(separator: ", ")): the request returned " +
                         "\"not granted\" and the status is still not determined.",
                hint: "The bridge must run as an installed, LaunchServices-launched foreground " +
                      "app for macOS to show the dialog. Reinstall with build-install.sh and " +
                      "rerun from ~/Applications, or grant access manually in System Settings.",
                recovery: RequestVerdict.recoveryCommands(for: notPresented)
            ), payload: object.filter { $0.key != "ok" && $0.key != "error" && $0.key != "command" })
        }

        print(Out.render(object))
        exit((object["ok"] as? Bool) == true ? 0 : 1)
    }
}

// MARK: - full disk access

enum FDACommand {
    static func run(_ args: Args) -> Never {
        let sub = args.positional(1) ?? "status"
        switch sub {
        case "status":
            Out.success("fda status", FullDiskAccess.status())
        case "open-settings", "help":
            var payload = FullDiskAccess.status()
            if sub == "open-settings" {
                payload["opened_settings"] = SettingsPane.fullDiskAccess.open()
            }
            payload["settings_url"] = SettingsPane.fullDiskAccess.url
            payload["settings_pane"] = SettingsPane.fullDiskAccess.label
            payload["requires_manual_user_action"] = true
            Out.success("fda \(sub)", payload)
        default:
            Out.failure("fda", BridgeError(
                code: "unknown_subcommand",
                message: "Unknown fda subcommand \"\(sub)\"",
                hint: "Available: status, open-settings, help"
            ))
        }
    }
}

// MARK: - help

enum Help {
    static func emit() -> Never {
        Out.success("help", [
            "usage": "letta-privacy-bridge <command> [subcommand] [options]",
            "output_contract": "stdout is always a single JSON object; stderr carries diagnostics only.",
            "commands": [
                ["name": "status", "summary": "Report every permission this bridge tracks."],
                ["name": "version", "summary": "Report version and installed bundle path."],
                ["name": "request [calendar|reminders|notes|mail|all]",
                 "summary": "Relaunch through LaunchServices and show grantable system dialogs.",
                 "options": ["--in-process", "--timeout <seconds>", "--result-file <path>"]],
                ["name": "calendar list", "summary": "List calendars.",
                 "options": ["--account <name>", "--with-counts"]],
                ["name": "calendar events", "summary": "List events in a range.",
                 "options": ["--start <date>", "--end <date>", "--days <n>",
                             "--calendar <name>", "--account <name>", "--limit <n>"]],
                ["name": "calendar create", "summary": "Create an event.",
                 "options": ["--calendar <name>", "--title <text>", "--start <datetime>",
                             "--end <datetime>", "--duration <minutes>", "--date <date> --all-day",
                             "--location <text>", "--notes <text>", "--url <url>"]],
                ["name": "reminders lists", "summary": "List reminder lists.",
                 "options": ["--account <name>", "--with-counts"]],
                ["name": "reminders list", "summary": "List reminders.",
                 "options": ["--list <name>", "--due-before <date>", "--due-after <date>",
                             "--include-completed", "--completed-only", "--limit <n>"]],
                ["name": "reminders create", "summary": "Create a reminder.",
                 "options": ["--title <text>", "--list <name>", "--due <datetime>",
                             "--notes <text>", "--priority <0-9>"]],
                ["name": "reminders complete", "summary": "Complete a reminder.", "options": ["--id <id>"]],
                ["name": "automation status", "summary": "Apple Events permission per app.",
                 "options": ["--app notes|mail|calendar|reminders"]],
                ["name": "automation request", "summary": "Trigger the Apple Events dialog.",
                 "options": ["--app <app>", "--no-launch"]],
                ["name": "automation probe",
                 "summary": "Bounded structural check (counts only, never content).",
                 "options": ["--app notes|mail"]],
                ["name": "notes|mail <status|request|probe>", "summary": "Shorthand for automation --app."],
                ["name": "notes folders", "summary": "List Notes folders with counts."],
                ["name": "notes list", "summary": "List note metadata; no bodies.",
                 "options": ["--folder <name>", "--recent <days>", "--limit <n>"]],
                ["name": "notes search", "summary": "Search titles, and bodies unless --title-only.",
                 "options": ["--query <text>", "--folder <name>", "--title-only",
                             "--preview", "--limit <n>"]],
                ["name": "notes read", "summary": "Read one note.",
                 "options": ["--title <text>", "--folder <name>", "--format text|html"]],
                ["name": "notes create", "summary": "Create a note.",
                 "options": ["--title <text>", "--body <text>", "--body-file <path>",
                             "--folder <name>", "--html"]],
                ["name": "notes move", "summary": "Move a note between folders.",
                 "options": ["--title <text>", "--from <name>", "--to <name>"]],
                ["name": "notes delete", "summary": "Delete a note; requires --confirmed.",
                 "options": ["--title <text>", "--folder <name>", "--confirmed"]],
                ["name": "notes folder-create|folder-rename|folder-delete",
                 "summary": "Folder management; folder-delete requires --confirmed and an empty folder.",
                 "options": ["--name <text>", "--parent <name>", "--new-name <text>", "--confirmed"]],
                ["name": "notes export", "summary": "Write a note or folder to disk.",
                 "options": ["--title <text> --output <path>",
                             "--folder <name> --output-dir <dir>",
                             "--format text|html", "--force"]],
                ["name": "notes help", "summary": "Full Notes subcommand reference."],
                ["name": "fda status", "summary": "Detect Full Disk Access; it cannot be requested."],
                ["name": "fda open-settings", "summary": "Open the Full Disk Access pane and print manual steps."],
                ["name": "open-settings <pane>",
                 "summary": "Open a Privacy pane.",
                 "options": SettingsPane.allCases.map(\.rawValue)],
            ],
            "notes": [
                "Full Disk Access cannot be requested by any app. macOS only accepts a " +
                "manual grant in System Settings; this bridge detects and links to it.",
                "Run `request` from the installed app so macOS attributes the prompt to " +
                "Letta Privacy Bridge rather than to the calling terminal.",
            ],
        ])
    }
}
