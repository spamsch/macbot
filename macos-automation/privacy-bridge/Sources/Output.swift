// ==============================================================================
// Output.swift - Structured JSON on stdout, diagnostics on stderr.
// ==============================================================================
// Every command prints exactly one JSON object on stdout. Human-readable
// progress notes go to stderr so callers can parse stdout unconditionally.
// ==============================================================================

import Foundation

/// Kept in sync with Resources/Info.plist by build-install.sh.
let bridgeVersion = "1.0.0"
let bridgeBundleID = "ai.letta.privacybridge"

struct BridgeError: Error {
    let code: String
    let message: String
    var hint: String?
    var recovery: [String] = []
}

enum Diag {
    static func log(_ message: String) {
        FileHandle.standardError.write(Data(("[letta-privacy-bridge] " + message + "\n").utf8))
    }
}

enum Out {
    /// Set once, at startup, when this process is the app-hosted child (see
    /// AppHost.swift). Its stdout goes nowhere the caller can read, so every
    /// result is mirrored to this file for the waiting parent to pick up.
    static var hostResultFile: String?

    /// Serializes `payload` deterministically (sorted keys) and writes it to stdout.
    static func render(_ payload: [String: Any]) -> String {
        guard JSONSerialization.isValidJSONObject(payload),
              let data = try? JSONSerialization.data(
                withJSONObject: payload,
                options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
              ),
              let text = String(data: data, encoding: .utf8)
        else {
            return "{\"ok\": false, \"error\": {\"code\": \"serialization_failed\", " +
                   "\"message\": \"Result could not be encoded as JSON\"}}"
        }
        return text
    }

    static func success(_ command: String, _ payload: [String: Any] = [:]) -> Never {
        success(command, payload, resultFile: nil)
    }

    /// Writes the payload to stdout and, when a result file was requested, to disk as well.
    static func success(_ command: String, _ payload: [String: Any], resultFile: String?) -> Never {
        var body = payload
        body["ok"] = true
        body["command"] = command
        body["bridge_version"] = bridgeVersion
        let text = render(body)
        if let path = resultFile ?? hostResultFile {
            writeResultFile(text, to: path)
        }
        print(text)
        exit(0)
    }

    static func failure(_ command: String, _ error: BridgeError, resultFile: String? = nil) -> Never {
        failure(command, error, payload: [:], resultFile: resultFile)
    }

    /// Failure that still carries the partial results it collected. `request`
    /// uses this: "no dialog appeared" is a failure, but the per-subject status
    /// it managed to read is exactly what the caller needs to act on.
    static func failure(
        _ command: String,
        _ error: BridgeError,
        payload: [String: Any],
        resultFile: String? = nil
    ) -> Never {
        var errorBody: [String: Any] = ["code": error.code, "message": error.message]
        if let hint = error.hint { errorBody["hint"] = hint }
        if !error.recovery.isEmpty { errorBody["recovery"] = error.recovery }
        var body = payload
        body["ok"] = false
        body["command"] = command
        body["bridge_version"] = bridgeVersion
        body["error"] = errorBody
        let text = render(body)
        if let path = resultFile ?? hostResultFile { writeResultFile(text, to: path) }
        print(text)
        Diag.log("\(error.code): \(error.message)")
        exit(1)
    }

    private static func writeResultFile(_ text: String, to path: String) {
        let url = URL(fileURLWithPath: path)
        try? FileManager.default.createDirectory(
            at: url.deletingLastPathComponent(), withIntermediateDirectories: true
        )
        // Write to a temp sibling first so a polling parent never reads a half file.
        let tmp = url.appendingPathExtension("partial")
        do {
            try Data(text.utf8).write(to: tmp)
            // Results can carry calendar, reminder, and note content: keep them
            // readable only by the user who asked for them.
            try? FileManager.default.setAttributes(
                [.posixPermissions: 0o600], ofItemAtPath: tmp.path
            )
            _ = try? FileManager.default.removeItem(at: url)
            try FileManager.default.moveItem(at: tmp, to: url)
        } catch {
            Diag.log("could not write result file \(path): \(error.localizedDescription)")
        }
    }
}

extension Date {
    var iso: String {
        let formatter = ISO8601DateFormatter()
        formatter.timeZone = TimeZone.current
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.string(from: self)
    }
}
