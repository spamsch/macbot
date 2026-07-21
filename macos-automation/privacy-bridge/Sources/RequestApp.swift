// ==============================================================================
// RequestApp.swift - The foreground AppKit application used by `request`.
// ==============================================================================
// Why this file exists:
//
// EventKit's `requestFullAccessToEvents(completion:)` does not present the TCC
// dialog itself. It hands the request to `tccd`, which asks the *responsible*
// process to display a system-modal sheet, then calls the completion handler on
// an internal queue. Two things have to be true for that to work:
//
//   1. The requesting process must be a real, launched application — one with a
//      connection to the window server and an activation policy that allows it
//      to own a foreground window. A plain Foundation CLI has neither, so the
//      request is filed against a process that can never show it: the status
//      stays `notDetermined`, no dialog appears, and the app never shows up in
//      the Calendars pane (TCC only creates an entry once a decision exists).
//   2. The process must run its main run loop while the request is in flight.
//      Blocking the main thread on a `DispatchSemaphore` deadlocks exactly the
//      thread the system needs in order to present and dismiss the sheet.
//
// So `request` runs as a minimal `NSApplication`: regular activation policy,
// activated, no windows and no menu bar of its own, authorization kicked off
// from `applicationDidFinishLaunching` and driven entirely by completion
// handlers. Nothing blocks. When the last completion returns we write the
// structured result and exit.
//
// Only `request` builds an NSApplication. Every other command stays a plain,
// noninteractive CLI process and never touches AppKit.
// ==============================================================================

import AppKit
import EventKit
import Foundation

enum RequestApp {
    /// `NSApplication.delegate` is a weak reference, so the delegate needs an
    /// owner that outlives the run loop.
    private static var retainedDelegate: RequestAppDelegate?

    static func run(subjects: [String], resultFile: String?, timeout: TimeInterval) -> Never {
        let app = NSApplication.shared

        // `.regular` is what makes this a foreground app for the window server:
        // it can be activated, it can own the frontmost window, and TCC will
        // present its dialog. The bundle no longer sets `LSUIElement`, so this
        // is a confirmation rather than a transition — see README, "Activation
        // policy". Setting it explicitly keeps the behaviour correct even when
        // the binary is invoked directly instead of through LaunchServices.
        app.setActivationPolicy(.regular)

        let delegate = RequestAppDelegate(
            subjects: subjects, resultFile: resultFile, timeout: timeout
        )
        retainedDelegate = delegate
        app.delegate = delegate

        if #available(macOS 14.0, *) {
            app.activate()
        } else {
            app.activate(ignoringOtherApps: true)
        }

        app.run()

        // `run()` returns only if something stopped the loop before the
        // authorization handlers finished. That is a failure, not a success.
        Out.failure("request", BridgeError(
            code: "event_loop_exited",
            message: "The request app's run loop exited before authorization completed",
            hint: "Rerun `letta-privacy-bridge request`, or grant access manually.",
            recovery: ["letta-privacy-bridge open-settings calendars",
                       "letta-privacy-bridge open-settings reminders"]
        ), resultFile: resultFile)
    }
}

// MARK: - delegate

final class RequestAppDelegate: NSObject, NSApplicationDelegate {
    private let subjects: [String]
    private let resultFile: String?
    private let timeout: TimeInterval

    private var results: [String: Any] = [:]
    private var next = 0
    /// EventKit completion handlers only fire while the store is alive.
    private var stores: [EKEventStore] = []
    private var watchdog: Timer?
    private var finished = false

    init(subjects: [String], resultFile: String?, timeout: TimeInterval) {
        self.subjects = subjects
        self.resultFile = resultFile
        self.timeout = timeout
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        if #available(macOS 14.0, *) {
            NSApp.activate()
        } else {
            NSApp.activate(ignoringOtherApps: true)
        }

        watchdog = Timer.scheduledTimer(withTimeInterval: timeout, repeats: false) { [weak self] _ in
            self?.finish(timedOut: true)
        }

        // Start after the launch notification has been fully delivered, so the
        // app is registered with the window server before TCC is asked to draw
        // on its behalf.
        DispatchQueue.main.async { [weak self] in self?.processNext() }
    }

    func applicationSupportsSecureRestorableState(_ app: NSApplication) -> Bool { true }

    // MARK: request chain

    /// One subject at a time: stacking two TCC sheets makes the second one
    /// invisible until the first is answered, which reads as a hang.
    private func processNext() {
        guard next < subjects.count else { return finish(timedOut: false) }
        let subject = subjects[next]
        next += 1

        switch subject {
        case "calendar":
            requestEventKit(.event, key: "calendar")
        case "reminders":
            requestEventKit(.reminder, key: "reminders")
        case "notes", "mail":
            requestAutomation(subject)
        default:
            processNext()
        }
    }

    private func requestEventKit(_ entity: EKEntityType, key: String) {
        Diag.log("requesting \(key) access…")
        let store = EventKitPermissions.requestFullAccess(entity) { [weak self] granted, status, error in
            guard let self else { return }
            var entry: [String: Any] = ["granted": granted, "authorization": status]
            if let error { entry["error"] = error }
            self.results[key] = entry
            Diag.log("\(key): granted=\(granted) status=\(status)")
            self.processNext()
        }
        stores.append(store)
    }

    /// `AEDeterminePermissionToAutomateTarget(askUser: true)` is synchronous and
    /// blocks until the Apple Events dialog is answered, so it runs off the main
    /// thread. The main run loop has to stay free.
    private func requestAutomation(_ subject: String) {
        guard let target = AutomationTarget.named(subject) else { return processNext() }
        Diag.log("requesting Apple Events access to \(target.displayName)…")
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let outcome = AutomationPermissions.request(target, launch: true)
            DispatchQueue.main.async {
                guard let self else { return }
                self.results[subject] = [
                    "granted": outcome.status == "authorized",
                    "authorization": outcome.status,
                    "os_status": Int(outcome.osStatus),
                    "detail": outcome.detail,
                ]
                Diag.log("\(subject): \(outcome.status)")
                self.processNext()
            }
        }
    }

    // MARK: result

    private func finish(timedOut: Bool) {
        guard !finished else { return }
        finished = true
        watchdog?.invalidate()
        watchdog = nil

        let pending = results.filter {
            ($0.value as? [String: Any])?["granted"] as? Bool != true
        }.keys.sorted()
        let missing = subjects.filter { results[$0] == nil }
        let notPresented = RequestVerdict.notPresented(in: results)

        var payload: [String: Any] = [
            "requested": subjects,
            "results": results,
            "all_granted": pending.isEmpty && missing.isEmpty,
            "pending": pending,
            "not_presented": notPresented,
            "timed_out": timedOut,
            "manual_steps": RequestVerdict.manualSteps(for: pending + missing),
        ]
        if !missing.isEmpty { payload["unanswered"] = missing }

        if timedOut {
            Out.failure("request", BridgeError(
                code: "request_timeout",
                message: "No answer within \(Int(timeout))s for: " +
                         (missing.isEmpty ? "(none)" : missing.joined(separator: ", ")),
                hint: "A system dialog is probably still open, or it was dismissed " +
                      "without an answer. Answer it and rerun, or grant access manually.",
                recovery: RequestVerdict.recoveryCommands(for: pending + missing)
            ), payload: payload, resultFile: resultFile)
        }

        if !notPresented.isEmpty {
            // The honest failure: the request returned, the user granted nothing,
            // and TCC still has no decision on file. That means no dialog was
            // ever shown — reporting this as success would be a lie.
            Out.failure("request", BridgeError(
                code: "authorization_not_presented",
                message: "macOS returned \"not granted\" for \(notPresented.joined(separator: ", ")) " +
                         "while the authorization status is still not determined, " +
                         "so no dialog was presented.",
                hint: "This usually means the app bundle is not the responsible process. " +
                      "Rebuild and reinstall the bridge, then run `request` again from the " +
                      "installed copy in ~/Applications. If it persists, grant access manually.",
                recovery: RequestVerdict.recoveryCommands(for: notPresented)
            ), payload: payload, resultFile: resultFile)
        }

        Out.success("request", payload, resultFile: resultFile)
    }
}

// MARK: - shared verdict logic

/// Used by both the in-process request app and the parent CLI that polls its
/// result file, so the two can never disagree about what counts as success.
enum RequestVerdict {
    /// Subjects that came back ungranted while TCC still holds no decision.
    /// A genuine denial ends in `denied`/`restricted`; `not_determined` after a
    /// completed request means the dialog never reached the user.
    static func notPresented(in results: [String: Any]) -> [String] {
        results.compactMap { key, value -> String? in
            guard let entry = value as? [String: Any],
                  entry["granted"] as? Bool != true,
                  let status = entry["authorization"] as? String,
                  status == "not_determined" || status == "undetermined_app_not_running"
            else { return nil }
            return key
        }.sorted()
    }

    static func manualSteps(for subjects: [String]) -> [String] {
        subjects.sorted().map { subject in
            switch subject {
            case "calendar": return "Enable Letta Privacy Bridge in \(SettingsPane.calendars.label)."
            case "reminders": return "Enable Letta Privacy Bridge in \(SettingsPane.reminders.label)."
            default: return "Enable \(subject.capitalized) under Letta Privacy Bridge in " +
                            "\(SettingsPane.automation.label)."
            }
        }
    }

    static func recoveryCommands(for subjects: [String]) -> [String] {
        var commands: [String] = []
        for subject in Set(subjects).sorted() {
            switch subject {
            case "calendar": commands.append("letta-privacy-bridge open-settings calendars")
            case "reminders": commands.append("letta-privacy-bridge open-settings reminders")
            default: commands.append("letta-privacy-bridge open-settings automation")
            }
        }
        return commands.isEmpty ? ["letta-privacy-bridge open-settings privacy"] : commands
    }
}
