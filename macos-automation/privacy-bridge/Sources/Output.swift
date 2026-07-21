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
        var body = payload
        body["ok"] = true
        body["command"] = command
        body["bridge_version"] = bridgeVersion
        print(render(body))
        exit(0)
    }

    /// Writes the payload to stdout and, when a result file was requested, to disk as well.
    static func success(_ command: String, _ payload: [String: Any], resultFile: String?) -> Never {
        var body = payload
        body["ok"] = true
        body["command"] = command
        body["bridge_version"] = bridgeVersion
        let text = render(body)
        if let path = resultFile {
            writeResultFile(text, to: path)
        }
        print(text)
        exit(0)
    }

    static func failure(_ command: String, _ error: BridgeError, resultFile: String? = nil) -> Never {
        var errorBody: [String: Any] = ["code": error.code, "message": error.message]
        if let hint = error.hint { errorBody["hint"] = hint }
        if !error.recovery.isEmpty { errorBody["recovery"] = error.recovery }
        let body: [String: Any] = [
            "ok": false,
            "command": command,
            "bridge_version": bridgeVersion,
            "error": errorBody,
        ]
        let text = render(body)
        if let path = resultFile { writeResultFile(text, to: path) }
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
