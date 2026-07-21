// ==============================================================================
// AutomationCommands.swift - Apple Events permission for Notes.app / Mail.app.
// ==============================================================================
// Scope on purpose: status, request, and a bounded structural probe. The probe
// returns counts only. It never returns note bodies, message bodies, senders,
// subjects, or addresses.
//
// Notes content operations live in NotesCommands.swift and are sent by this
// process too, so they run under this app's Automation grant. Mail content is
// still handled by `managing-email` over IMAP/Graph, which needs no Apple Event.
// ==============================================================================

import Foundation

enum AutomationCommands {
    static func run(_ args: Args) -> Never {
        let sub = args.positional(1) ?? "status"
        switch sub {
        case "status": status(args)
        case "request": request(args)
        case "probe": probe(args)
        default:
            Out.failure("automation", BridgeError(
                code: "unknown_subcommand",
                message: "Unknown automation subcommand \"\(sub)\"",
                hint: "Available: status, request, probe"
            ))
        }
    }

    private static func target(_ args: Args, command: String) -> AutomationTarget {
        let key = args.string("app") ?? args.positional(2) ?? ""
        guard let target = AutomationTarget.named(key) else {
            Out.failure(command, BridgeError(
                code: "unknown_app",
                message: key.isEmpty ? "Missing --app" : "Unsupported --app \"\(key)\"",
                hint: "Supported: " + AutomationTarget.all.map(\.key).joined(separator: ", ")
            ))
        }
        return target
    }

    private static func status(_ args: Args) -> Never {
        let command = "automation status"
        if args.string("app") == nil, args.positional(2) == nil {
            let all = AutomationTarget.all.map { entry -> [String: Any] in
                let result = AutomationPermissions.check(entry, askUser: false)
                return [
                    "app": entry.key,
                    "bundle_id": entry.bundleID,
                    "status": result.status,
                    "os_status": Int(result.osStatus),
                    "detail": result.detail,
                ]
            }
            Out.success(command, ["targets": all])
        }
        let entry = target(args, command: command)
        let result = AutomationPermissions.check(entry, askUser: false)
        Out.success(command, [
            "app": entry.key,
            "bundle_id": entry.bundleID,
            "status": result.status,
            "os_status": Int(result.osStatus),
            "detail": result.detail,
            "settings_pane": SettingsPane.automation.label,
        ])
    }

    private static func request(_ args: Args) -> Never {
        let command = "automation request"
        let entry = target(args, command: command)
        // Launching the target hidden is what makes macOS able to show a decision
        // dialog. `--no-launch` keeps the call completely passive.
        let result = AutomationPermissions.request(entry, launch: !args.bool("no-launch"))
        let granted = result.status == "authorized"
        Out.success(command, [
            "app": entry.key,
            "bundle_id": entry.bundleID,
            "status": result.status,
            "os_status": Int(result.osStatus),
            "granted": granted,
            "launched_target": result.launched,
            "detail": result.detail,
            "next_step": granted
                ? "No action needed."
                : "Approve \"Letta Privacy Bridge\" for \(entry.displayName) in System Settings > " +
                  "\(SettingsPane.automation.label), then rerun this command.",
        ])
    }

    // MARK: bounded probe

    private static func probe(_ args: Args) -> Never {
        let command = "automation probe"
        let entry = target(args, command: command)

        let script: String
        let keys: [String]
        switch entry.key {
        case "notes":
            // Structural only: how many folders and notes exist. No titles, no bodies.
            keys = ["folders", "notes"]
            script = """
            tell application "Notes"
                return {(count of folders) as text, (count of notes) as text}
            end tell
            """
        case "mail":
            // Structural only: account and mailbox counts plus the unread total.
            // No addresses, subjects, senders, or bodies.
            keys = ["accounts", "mailboxes", "inbox_unread"]
            script = """
            tell application "Mail"
                return {(count of accounts) as text, (count of mailboxes) as text, ¬
                    (unread count of inbox) as text}
            end tell
            """
        default:
            Out.failure(command, BridgeError(
                code: "probe_unsupported",
                message: "No bounded probe is defined for \"\(entry.key)\"",
                hint: "Probes exist for: notes, mail"
            ))
        }

        let permission = AutomationPermissions.check(entry, askUser: false)
        if permission.status == "denied" {
            Out.failure(command, BridgeError(
                code: "automation_denied",
                message: "Apple Events to \(entry.displayName) are denied for this app",
                hint: permission.detail,
                recovery: [
                    "letta-privacy-bridge automation request --app \(entry.key)",
                    "letta-privacy-bridge open-settings automation",
                ]
            ))
        }

        let result = AppleScriptRunner.runOrFail(script, command: command, app: entry.key)
        var counts: [String: Any] = [:]
        for (offset, key) in keys.enumerated() {
            counts[key] = result.int(offset + 1)
        }

        Out.success(command, [
            "app": entry.key,
            "status": "authorized",
            "counts": counts,
            "note": "Counts only. This probe never reads message or note content.",
        ])
    }
}
