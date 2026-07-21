// ==============================================================================
// Args.swift - Minimal, predictable argument parsing.
// ==============================================================================
// Rules:
//   --key value   -> string option
//   --flag        -> boolean option (must be declared in `booleanFlags`)
//   everything else, in order, is a positional argument
// ==============================================================================

import Foundation

struct Args {
    private var options: [String: String] = [:]
    private var flags: Set<String> = []
    private(set) var positionals: [String] = []

    /// Options that never take a value. Declared globally so parsing stays
    /// context-free and a typo cannot silently swallow the next argument.
    static let booleanFlags: Set<String> = [
        "all-day", "with-counts", "include-completed", "completed-only",
        "in-process", "launch", "no-launch", "help", "confirmed",
        // Internal: set by AppHost when relaunching through LaunchServices.
        "letta-hosted",
        "html", "title-only", "preview", "force", "dry-run",
    ]

    init(_ argv: [String]) {
        var index = 0
        while index < argv.count {
            let token = argv[index]
            if token.hasPrefix("--") {
                let name = String(token.dropFirst(2))
                if Args.booleanFlags.contains(name) {
                    flags.insert(name)
                    index += 1
                } else if index + 1 < argv.count, !argv[index + 1].hasPrefix("--") {
                    options[name] = argv[index + 1]
                    index += 2
                } else {
                    // Unknown bare `--name`: treat as a flag rather than eating a value.
                    flags.insert(name)
                    index += 1
                }
            } else {
                positionals.append(token)
                index += 1
            }
        }
    }

    func string(_ name: String) -> String? {
        guard let value = options[name], !value.isEmpty else { return nil }
        return value
    }

    func require(_ name: String, command: String) -> String {
        guard let value = string(name) else {
            Out.failure(command, BridgeError(
                code: "missing_argument",
                message: "Required option --\(name) is missing",
                hint: "Run `letta-privacy-bridge help` for the command reference."
            ))
        }
        return value
    }

    func int(_ name: String) -> Int? {
        guard let value = options[name] else { return nil }
        return Int(value)
    }

    func bool(_ name: String) -> Bool { flags.contains(name) }

    func positional(_ index: Int) -> String? {
        index < positionals.count ? positionals[index] : nil
    }
}

enum DateParsing {
    /// Accepts "YYYY-MM-DD HH:MM", "YYYY-MM-DD HH:MM:SS", "YYYY-MM-DDTHH:MM(:SS)",
    /// "YYYY-MM-DD" and full ISO-8601 with offset. Bare forms are local time.
    static func parse(_ raw: String) -> Date? {
        let value = raw.trimmingCharacters(in: .whitespaces)

        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime]
        if let date = iso.date(from: value) { return date }

        let patterns = [
            "yyyy-MM-dd HH:mm:ss",
            "yyyy-MM-dd'T'HH:mm:ss",
            "yyyy-MM-dd HH:mm",
            "yyyy-MM-dd'T'HH:mm",
            "yyyy-MM-dd",
        ]
        for pattern in patterns {
            let formatter = DateFormatter()
            formatter.locale = Locale(identifier: "en_US_POSIX")
            formatter.timeZone = TimeZone.current
            formatter.dateFormat = pattern
            if let date = formatter.date(from: value) { return date }
        }
        return nil
    }

    static func require(_ raw: String, command: String, option: String) -> Date {
        guard let date = parse(raw) else {
            Out.failure(command, BridgeError(
                code: "invalid_date",
                message: "Could not parse --\(option) value \"\(raw)\"",
                hint: "Use \"YYYY-MM-DD\", \"YYYY-MM-DD HH:MM\", or full ISO-8601."
            ))
        }
        return date
    }

    static func startOfToday() -> Date { Calendar.current.startOfDay(for: Date()) }
}
