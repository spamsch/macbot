// ==============================================================================
// AppHost.swift - Transparent app hosting for permission-bound commands.
// ==============================================================================
// The problem this solves:
//
// TCC does not authorize a *binary*, it authorizes the process that is
// *responsible* for the request. When you run
//
//     ~/Applications/Letta Privacy Bridge.app/Contents/MacOS/letta-privacy-bridge \
//         calendar events --days 1
//
// straight from a shell, launchd never launched an application: the terminal
// (or whatever agent spawned it) stays the responsible process, so EventKit
// answers with the *terminal's* Calendar grant. That is why `request` could
// report `authorized` — it relaunched through LaunchServices — while the very
// next direct `calendar events` still saw `not_determined`. Two different TCC
// subjects, one binary.
//
// The fix is to make hosting invisible to the caller. Anything that touches
// Calendar, Reminders, or Apple Events is re-launched through LaunchServices
// (`open -n -a <bundle>`), so macOS launches the installed app and the app is
// its own responsible process. The child runs the same argument vector plus an
// internal marker, writes its JSON verdict to a private file in the per-user
// temporary directory, and exits. The parent polls that file, prints exactly
// the child's JSON on stdout, and exits with the child's status.
//
// Callers keep using one binary and one JSON contract. They never see the
// relay, the marker, or the temporary path.
//
// Invariants:
//   * The child never relays again — it carries `--letta-hosted`, and hosting
//     is decided before any command dispatch. One hop, always.
//   * Marker options coming in from the outside are stripped before the child's
//     argument vector is built, so a caller cannot inject a result path.
//   * Data commands launch with `open -g` (no activation, no window, no focus
//     steal). Only request flows, which must present a dialog, come forward.
//   * The temporary result path never appears in stdout or in an error message.
// ==============================================================================

import Foundation

enum AppHost {
    /// Internal marker: "you are the hosted child, execute, do not relay".
    static let markerFlag = "letta-hosted"
    /// Internal option carrying the file the child writes its JSON verdict to.
    static let resultOption = "letta-result"

    /// Seconds a relayed data command may take before the parent gives up.
    private static let defaultTimeout: TimeInterval = 120

    // MARK: - routing

    /// True when `command` reaches Calendar, Reminders, or Apple Events and
    /// therefore has to execute inside the installed app.
    ///
    /// Deliberately excluded: `help`, `version`, `fda …` (Full Disk Access is
    /// detected by reading a protected path from *this* process, and cannot be
    /// requested by anyone), and `open-settings` (it only shells out to `open`).
    /// `status` *is* included: an authorization status read outside the app
    /// describes the caller's grants, not the bridge's, which is precisely the
    /// misreport this file exists to prevent.
    static func requiresHost(command: String, args: Args) -> Bool {
        let sub = (args.positional(1) ?? "help").lowercased()
        switch command {
        case "status":
            return true
        case "calendar", "reminders", "automation", "notes", "mail":
            // `<group> help` is a static reference page; it touches nothing.
            return sub != "help"
        default:
            // `request` hosts itself through RequestApp; see RequestCommand.
            return false
        }
    }

    /// Called once, before dispatch. Returns normally when this process should
    /// execute the command itself; otherwise it relays and never returns.
    static func interceptOrPrepare(command: String, arguments: [String], args: Args) {
        if args.bool(markerFlag) {
            // Hosted child: stdout is not connected to the caller, so every
            // Out.success/Out.failure must also land in the result file.
            Out.hostResultFile = args.string(resultOption)
            return
        }
        guard requiresHost(command: command, args: args) else { return }
        guard Bundle.main.bundleIdentifier != nil else {
            // A loose binary outside an app bundle cannot be launched by
            // LaunchServices. Run it directly and say so on stderr — the
            // result is still valid, it is just attributed to the caller.
            Diag.log("not running from an app bundle; executing \"\(command)\" directly. " +
                     "Permission results describe the calling process, not the bridge.")
            return
        }

        let timeout = TimeInterval(args.int("timeout") ?? Int(defaultTimeout))
        // Reads must not steal focus; a request has a dialog to show.
        let showsDialog = (args.positional(1) ?? "").lowercased() == "request"
        let verdict = launchAndAwait(
            childArguments: passthrough(arguments),
            resultOption: resultOption,
            extraArguments: ["--\(markerFlag)"],
            foreground: showsDialog,
            timeout: max(10, timeout),
            command: command
        )
        print(Out.render(verdict))
        exit((verdict["ok"] as? Bool) == true ? 0 : 1)
    }

    // MARK: - argument passthrough

    /// Strips our internal marker options and LaunchServices' `-psn_…` noise,
    /// then validates what remains. Nothing here is interpreted by a shell —
    /// `open` receives the vector as argv — but a hostile argument should still
    /// fail loudly rather than travel to the child.
    static func passthrough(_ arguments: [String]) -> [String] {
        var result: [String] = []
        var index = 0
        while index < arguments.count {
            let token = arguments[index]
            if token == "--\(markerFlag)" {
                index += 1
                continue
            }
            if token == "--\(resultOption)" {
                // Skip the option and its value, if it has one.
                index += (index + 1 < arguments.count && !arguments[index + 1].hasPrefix("--")) ? 2 : 1
                continue
            }
            if token.hasPrefix("-psn_") {
                index += 1
                continue
            }
            result.append(token)
            index += 1
        }
        validate(result)
        return result
    }

    private static func validate(_ arguments: [String]) {
        guard arguments.count <= 128 else {
            Out.failure("host", BridgeError(
                code: "too_many_arguments",
                message: "Refusing to relay \(arguments.count) arguments (limit 128)",
                hint: "Split the work into smaller invocations."
            ))
        }
        for argument in arguments {
            guard argument.utf8.count <= 8192 else {
                Out.failure("host", BridgeError(
                    code: "argument_too_long",
                    message: "An argument exceeds the 8192-byte relay limit",
                    hint: "Pass long note bodies with --body-file instead of --body."
                ))
            }
            guard !argument.unicodeScalars.contains(where: { $0.value < 0x20 && $0 != "\n" && $0 != "\t" })
            else {
                Out.failure("host", BridgeError(
                    code: "invalid_argument",
                    message: "An argument contains control characters and was not relayed",
                    hint: "Remove control characters, or pass the text via --body-file."
                ))
            }
        }
    }

    // MARK: - launch and collect

    /// Launches the installed bundle through LaunchServices with
    /// `childArguments + [--<resultOption> <private path>] + extraArguments`,
    /// waits for the child's JSON verdict, and returns it.
    ///
    /// - Parameter foreground: `false` uses `open -g`, which starts the app
    ///   without activating it — no Dock bounce, no focus steal for reads.
    ///   Request flows pass `true` because their dialog has to come forward.
    /// - Parameter timeoutError: replaces the generic "no answer" failure when
    ///   the caller can say something more useful about what is stuck.
    static func launchAndAwait(
        childArguments: [String],
        resultOption: String,
        extraArguments: [String] = [],
        foreground: Bool,
        timeout: TimeInterval,
        command: String,
        timeoutError: BridgeError? = nil
    ) -> [String: Any] {
        let resultPath = NSTemporaryDirectory() +
            "letta-privacy-bridge-\(UUID().uuidString).json"
        defer { try? FileManager.default.removeItem(atPath: resultPath) }

        var openArguments = ["-n"]
        if !foreground { openArguments.append("-g") }
        openArguments += ["-a", Bundle.main.bundleURL.path, "--args"]
        openArguments += childArguments
        openArguments += ["--\(resultOption)", resultPath]
        openArguments += extraArguments

        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/usr/bin/open")
        task.arguments = openArguments
        do {
            try task.run()
            task.waitUntilExit()
        } catch {
            Out.failure(command, BridgeError(
                code: "host_launch_failed",
                message: "Could not launch the bridge app through LaunchServices: " +
                         error.localizedDescription,
                hint: "Reinstall the app, then rerun.",
                recovery: ["bash macos-automation/privacy-bridge/build-install.sh"]
            ))
        }
        guard task.terminationStatus == 0 else {
            Out.failure(command, BridgeError(
                code: "host_launch_failed",
                message: "`open` exited with status \(task.terminationStatus)",
                hint: "Confirm the app exists at \(Bundle.main.bundleURL.path)."
            ))
        }

        Diag.log("waiting for the hosted app to answer \"\(command)\" (up to \(Int(timeout))s)…")
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if let data = FileManager.default.contents(atPath: resultPath),
               let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                return object
            }
            Thread.sleep(forTimeInterval: 0.1)
        }

        Out.failure(command, timeoutError ?? BridgeError(
            code: "host_timeout",
            message: "The hosted app did not answer \"\(command)\" within \(Int(timeout))s",
            hint: "The app may be waiting on a system dialog, or an automated app " +
                  "(Notes, Mail) may be busy. Answer any open dialog and rerun, " +
                  "or raise --timeout.",
            recovery: ["letta-privacy-bridge status"]
        ))
    }
}
