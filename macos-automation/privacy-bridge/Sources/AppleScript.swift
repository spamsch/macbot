// ==============================================================================
// AppleScript.swift - In-process Apple Events via NSAppleScript.
// ==============================================================================
// Why in-process and not `osascript`:
//   TCC attributes an Apple Event to the process that sends it. Shelling out to
//   /usr/bin/osascript makes *osascript* the caller, so the Automation grant
//   lands on a different identity than this app's bundle ID — exactly the
//   scattered-grant problem the bridge exists to fix. NSAppleScript sends the
//   event from this binary, inside this bundle, under `ai.letta.privacybridge`.
//
// Everything here returns raw NSAppleEventDescriptors. Scripts are written to
// return AppleScript lists so results decode without delimiter guessing: no
// separator character can collide with note text.
// ==============================================================================

import Foundation

struct AppleScriptFailure: Error {
    let number: Int
    let message: String
}

enum AppleScriptRunner {
    /// Compiles and runs `source` in this process. Returns the result descriptor
    /// or a structured failure carrying the OSA error number.
    static func run(_ source: String) -> Result<NSAppleEventDescriptor, AppleScriptFailure> {
        guard let script = NSAppleScript(source: source) else {
            return .failure(AppleScriptFailure(number: 0, message: "Script source could not be initialized"))
        }
        var errorInfo: NSDictionary?
        let result = script.executeAndReturnError(&errorInfo)
        if let error = errorInfo {
            let number = (error[NSAppleScript.errorNumber] as? Int) ?? 0
            let message = (error[NSAppleScript.errorMessage] as? String)
                ?? (error[NSAppleScript.errorBriefMessage] as? String)
                ?? "AppleScript failed with error \(number)"
            return .failure(AppleScriptFailure(number: number, message: message))
        }
        return .success(result)
    }

    /// Runs `source` or exits with a mapped bridge error. Used by every command
    /// that talks to an app, so the failure vocabulary stays identical.
    static func runOrFail(_ source: String, command: String, app: String) -> NSAppleEventDescriptor {
        switch run(source) {
        case .success(let descriptor):
            return descriptor
        case .failure(let failure):
            Out.failure(command, mapError(failure, app: app))
        }
    }

    static func mapError(_ failure: AppleScriptFailure, app: String) -> BridgeError {
        switch failure.number {
        case -1743, -10004:
            return BridgeError(
                code: "automation_denied",
                message: "Apple Events to \(app.capitalized) are not permitted for Letta Privacy Bridge",
                hint: "Approve \"Letta Privacy Bridge\" for \(app.capitalized) under " +
                      "System Settings > Privacy & Security > Automation.",
                recovery: [
                    "letta-privacy-bridge automation request --app \(app)",
                    "letta-privacy-bridge open-settings automation",
                ]
            )
        case -600:
            return BridgeError(
                code: "app_not_running",
                message: "\(app.capitalized) is not running",
                hint: "Launch it, or run `automation request --app \(app)` which starts it hidden.",
                recovery: ["letta-privacy-bridge automation request --app \(app)"]
            )
        case -1728:
            return BridgeError(
                code: "object_not_found",
                message: failure.message,
                hint: "\(app.capitalized) could not resolve one of the referenced objects. " +
                      "Confirm the folder or note name with a list command first."
            )
        case -128:
            return BridgeError(
                code: "user_cancelled",
                message: "The operation was cancelled"
            )
        default:
            return BridgeError(
                code: "applescript_error",
                message: failure.message,
                hint: "AppleScript error \(failure.number)."
            )
        }
    }
}

// MARK: - literal escaping

enum AS {
    /// Renders `value` as an AppleScript string literal. Newlines, tabs, quotes
    /// and backslashes are escaped, so no caller input can terminate the literal
    /// or inject statements.
    static func literal(_ value: String) -> String {
        var escaped = ""
        escaped.reserveCapacity(value.count + 2)
        for character in value.unicodeScalars {
            switch character {
            case "\\": escaped += "\\\\"
            case "\"": escaped += "\\\""
            case "\n": escaped += "\\n"
            case "\r": escaped += "\\r"
            case "\t": escaped += "\\t"
            default: escaped.unicodeScalars.append(character)
            }
        }
        return "\"" + escaped + "\""
    }
}

// MARK: - descriptor decoding

extension NSAppleEventDescriptor {
    /// AppleScript lists are 1-indexed; this flattens one level into an array.
    var items: [NSAppleEventDescriptor] {
        let count = numberOfItems
        guard count > 0 else { return [] }
        return (1...count).compactMap { atIndex($0) }
    }

    var text: String { stringValue ?? "" }

    func text(_ index: Int) -> String { atIndex(index)?.stringValue ?? "" }

    func int(_ index: Int) -> Int { Int(atIndex(index)?.stringValue ?? "") ?? 0 }
}
