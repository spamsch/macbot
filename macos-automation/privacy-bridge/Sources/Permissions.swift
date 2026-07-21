// ==============================================================================
// Permissions.swift - TCC status reporting, requests, and Settings deep links.
// ==============================================================================
// What this file can and cannot do, precisely:
//   * Calendars / Reminders  -> the app can request access; macOS shows a dialog.
//   * Apple Events (Notes/Mail) -> the app can request access; macOS shows a dialog.
//   * Full Disk Access       -> macOS does NOT allow any app to request or grant
//                               FDA. We can only detect it and open the pane.
// ==============================================================================

import CoreServices
import EventKit
import Foundation

enum SettingsPane: String, CaseIterable {
    case calendars
    case reminders
    case automation
    case fullDiskAccess = "full-disk-access"
    case privacy

    var url: String {
        switch self {
        case .calendars: return "x-apple.systempreferences:com.apple.preference.security?Privacy_Calendars"
        case .reminders: return "x-apple.systempreferences:com.apple.preference.security?Privacy_Reminders"
        case .automation: return "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation"
        case .fullDiskAccess: return "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"
        case .privacy: return "x-apple.systempreferences:com.apple.preference.security?Privacy"
        }
    }

    var label: String {
        switch self {
        case .calendars: return "Privacy & Security > Calendars"
        case .reminders: return "Privacy & Security > Reminders"
        case .automation: return "Privacy & Security > Automation"
        case .fullDiskAccess: return "Privacy & Security > Full Disk Access"
        case .privacy: return "Privacy & Security"
        }
    }

    @discardableResult
    func open() -> Bool {
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/usr/bin/open")
        task.arguments = [url]
        do {
            try task.run()
            task.waitUntilExit()
            return task.terminationStatus == 0
        } catch {
            Diag.log("failed to open \(url): \(error.localizedDescription)")
            return false
        }
    }
}

// MARK: - EventKit

enum EventKitPermissions {
    static func statusName(for entity: EKEntityType) -> String {
        switch EKEventStore.authorizationStatus(for: entity) {
        case .notDetermined: return "not_determined"
        case .restricted: return "restricted"
        case .denied: return "denied"
        case .authorized: return "authorized"
        case .fullAccess: return "full_access"
        case .writeOnly: return "write_only"
        @unknown default: return "unknown"
        }
    }

    static func hasFullAccess(_ entity: EKEntityType) -> Bool {
        // Deployment target is macOS 14, so `.fullAccess` is the only "yes".
        return EKEventStore.authorizationStatus(for: entity) == .fullAccess
    }

    /// Triggers the system dialog when the status is `not_determined`.
    ///
    /// Asynchronous by construction: EventKit needs the caller's main run loop
    /// free while TCC presents the sheet, so this never blocks and never uses a
    /// semaphore. `completion` is always delivered on the main queue.
    ///
    /// The returned store must be kept alive by the caller — EventKit drops the
    /// pending request (and never calls back) once the store is deallocated.
    /// Only `RequestApp` calls this; it runs inside an NSApplication that can
    /// actually own the dialog.
    static func requestFullAccess(
        _ entity: EKEntityType,
        completion: @escaping (_ granted: Bool, _ status: String, _ error: String?) -> Void
    ) -> EKEventStore {
        let store = EKEventStore()

        let handler: (Bool, Error?) -> Void = { granted, error in
            let message = error?.localizedDescription
            DispatchQueue.main.async {
                completion(granted, statusName(for: entity), message)
            }
        }

        if #available(macOS 14.0, *) {
            switch entity {
            case .event: store.requestFullAccessToEvents(completion: handler)
            case .reminder: store.requestFullAccessToReminders(completion: handler)
            @unknown default:
                DispatchQueue.main.async { completion(false, "unknown", "Unsupported entity type") }
            }
        } else {
            store.requestAccess(to: entity, completion: handler)
        }

        return store
    }

    /// Returns a store that already holds full access, or fails with an
    /// actionable error describing exactly how to grant it.
    ///
    /// Deliberately does **not** request access. Data commands are
    /// noninteractive and deterministic: they either have the grant and answer,
    /// or they fail immediately and tell the caller to run `request`. Prompting
    /// from here would make `calendar events` hang on a dialog that a plain CLI
    /// process cannot present anyway.
    static func authorizedStore(_ entity: EKEntityType, command: String) -> EKEventStore {
        guard hasFullAccess(entity) else {
            let subject = entity == .event ? "Calendars" : "Reminders"
            let pane: SettingsPane = entity == .event ? .calendars : .reminders
            Out.failure(command, BridgeError(
                code: entity == .event ? "calendar_access_denied" : "reminders_access_denied",
                message: "Letta Privacy Bridge does not have full access to \(subject) " +
                         "(status: \(statusName(for: entity)))",
                hint: statusName(for: entity) == "not_determined"
                    ? "Nobody has been asked yet. Run `request` — it launches the app in the "
                      + "foreground so macOS can show a grantable dialog — or grant access "
                      + "manually in System Settings > \(pane.label)."
                    : "Grant access in System Settings > \(pane.label), then retry.",
                recovery: [
                    "letta-privacy-bridge request \(entity == .event ? "calendar" : "reminders")",
                    "letta-privacy-bridge open-settings \(pane.rawValue)",
                ]
            ))
        }
        return EKEventStore()
    }
}

// MARK: - Apple Events / Automation

struct AutomationTarget {
    let key: String
    let bundleID: String
    let displayName: String

    static let all: [AutomationTarget] = [
        AutomationTarget(key: "notes", bundleID: "com.apple.Notes", displayName: "Notes"),
        AutomationTarget(key: "mail", bundleID: "com.apple.mail", displayName: "Mail"),
        AutomationTarget(key: "calendar", bundleID: "com.apple.iCal", displayName: "Calendar"),
        AutomationTarget(key: "reminders", bundleID: "com.apple.reminders", displayName: "Reminders"),
    ]

    static func named(_ key: String) -> AutomationTarget? {
        all.first { $0.key == key.lowercased() }
    }
}

enum AutomationPermissions {
    /// Wraps `AEDeterminePermissionToAutomateTarget`. With `askUser == false` this
    /// never prompts and never launches the target app.
    static func check(_ target: AutomationTarget, askUser: Bool) -> (status: String, osStatus: Int32, detail: String) {
        var address = AEAddressDesc()
        var bytes = Array(target.bundleID.utf8)
        let createStatus = AECreateDesc(
            DescType(typeApplicationBundleID), &bytes, bytes.count, &address
        )
        guard createStatus == noErr else {
            return ("unknown", Int32(createStatus), "Could not build an Apple Event address descriptor")
        }
        defer { AEDisposeDesc(&address) }

        let status = AEDeterminePermissionToAutomateTarget(
            &address, AEEventClass(typeWildCard), AEEventID(typeWildCard), askUser
        )
        return (name(for: status), status, describe(status, target: target))
    }

    static func name(for status: OSStatus) -> String {
        switch status {
        case noErr: return "authorized"
        case OSStatus(errAEEventNotPermitted): return "denied"
        case OSStatus(errAEEventWouldRequireUserConsent): return "not_determined"
        case OSStatus(procNotFound): return "undetermined_app_not_running"
        default: return "unknown"
        }
    }

    static func describe(_ status: OSStatus, target: AutomationTarget) -> String {
        switch status {
        case noErr:
            return "This app may send Apple Events to \(target.displayName)."
        case OSStatus(errAEEventNotPermitted):
            return "Automation of \(target.displayName) is denied. Enable it under " +
                   "System Settings > Privacy & Security > Automation > Letta Privacy Bridge."
        case OSStatus(errAEEventWouldRequireUserConsent):
            return "macOS has not asked yet. Run `automation request --app \(target.key)` " +
                   "to trigger the dialog."
        case OSStatus(procNotFound):
            return "\(target.displayName) is not running, so macOS cannot report a decision. " +
                   "Run `automation request --app \(target.key)` (it launches the app hidden) " +
                   "to determine the real status."
        default:
            return "Unexpected Apple Event status \(status)."
        }
    }

    /// Launches the target app hidden (`open -g -j`) so macOS has a live process to
    /// evaluate, then asks for consent. Blocks on the dialog.
    static func request(_ target: AutomationTarget, launch: Bool, timeout: TimeInterval = 15) -> (status: String, osStatus: Int32, detail: String, launched: Bool) {
        var launched = false
        let running = { !NSWorkspaceLite.isRunning(bundleID: target.bundleID) }
        if launch, running() {
            launched = NSWorkspaceLite.launchHidden(bundleID: target.bundleID)
            let deadline = Date().addingTimeInterval(timeout)
            while running(), Date() < deadline {
                Thread.sleep(forTimeInterval: 0.25)
            }
        }
        let result = check(target, askUser: true)
        return (result.status, result.osStatus, result.detail, launched)
    }
}

/// Thin shims over `open`/`pgrep` so the binary does not need to link AppKit.
enum NSWorkspaceLite {
    static func isRunning(bundleID: String) -> Bool {
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/bin/sh")
        // `lsappinfo` is the cheapest reliable check that does not launch anything.
        task.arguments = ["-c", "/usr/bin/lsappinfo info -only bundleid \(shellQuote(bundleID)) 2>/dev/null | grep -q ."]
        do {
            try task.run()
            task.waitUntilExit()
            return task.terminationStatus == 0
        } catch {
            return false
        }
    }

    /// `-g` keeps focus in the caller, `-j` launches hidden. No windows are shown
    /// and no document is opened.
    static func launchHidden(bundleID: String) -> Bool {
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/usr/bin/open")
        task.arguments = ["-g", "-j", "-b", bundleID]
        do {
            try task.run()
            task.waitUntilExit()
            return task.terminationStatus == 0
        } catch {
            Diag.log("could not launch \(bundleID): \(error.localizedDescription)")
            return false
        }
    }

    static func shellQuote(_ value: String) -> String {
        "'" + value.replacingOccurrences(of: "'", with: "'\\''") + "'"
    }
}

// MARK: - Full Disk Access

enum FullDiskAccess {
    /// FDA cannot be requested programmatically. It is detected by trying to open
    /// a file that only FDA-holders may read. We open and immediately close the
    /// descriptor; no bytes are read and no content is reported.
    static func status() -> [String: Any] {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        let probes: [(String, String)] = [
            ("tcc_db", home + "/Library/Application Support/com.apple.TCC/TCC.db"),
            ("mail_container", home + "/Library/Mail"),
            ("safari_container", home + "/Library/Safari"),
        ]

        var results: [String: Any] = [:]
        var anyReadable = false
        for (key, path) in probes {
            let readable = canOpenForReading(path)
            results[key] = ["path": path, "readable": readable]
            if readable { anyReadable = true }
        }

        return [
            "granted": anyReadable,
            "can_be_requested_programmatically": false,
            "probes": results,
            "explanation": "macOS does not expose an API for an app to request or grant " +
                           "Full Disk Access. TCC only accepts a manual grant made by the " +
                           "user in System Settings. This bridge can detect the state and " +
                           "open the correct pane; it cannot prompt for it.",
            "manual_steps": [
                "Open System Settings > Privacy & Security > Full Disk Access " +
                "(`letta-privacy-bridge fda open-settings`).",
                "Unlock with Touch ID or your password if the list is dimmed.",
                "Click + and add ~/Applications/Letta Privacy Bridge.app, or toggle it on " +
                "if it is already listed.",
                "Quit and relaunch any process that needs the new access; TCC caches the " +
                "decision per running process.",
            ],
        ]
    }

    private static func canOpenForReading(_ path: String) -> Bool {
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: path, isDirectory: &isDirectory) else {
            return false
        }
        if isDirectory.boolValue {
            // Listing a protected directory is enough of a signal; entry names are
            // counted, never returned.
            return (try? FileManager.default.contentsOfDirectory(atPath: path)) != nil
        }
        let descriptor = open(path, O_RDONLY)
        if descriptor >= 0 {
            close(descriptor)
            return true
        }
        return false
    }
}
