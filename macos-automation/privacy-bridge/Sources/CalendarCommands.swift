// ==============================================================================
// CalendarCommands.swift - EventKit calendar reads and event creation.
// ==============================================================================

import EventKit
import Foundation

enum CalendarCommands {
    static func run(_ args: Args) -> Never {
        let sub = args.positional(1) ?? "help"
        switch sub {
        case "list", "list-calendars": listCalendars(args)
        case "events": events(args)
        case "create", "create-event": createEvent(args)
        case "status": status()
        default:
            Out.failure("calendar", BridgeError(
                code: "unknown_subcommand",
                message: "Unknown calendar subcommand \"\(sub)\"",
                hint: "Available: list, events, create, status"
            ))
        }
    }

    private static func status() -> Never {
        Out.success("calendar status", [
            "authorization": EventKitPermissions.statusName(for: .event),
            "full_access": EventKitPermissions.hasFullAccess(.event),
        ])
    }

    // MARK: list

    private static func listCalendars(_ args: Args) -> Never {
        let command = "calendar list"
        let store = EventKitPermissions.authorizedStore(.event, command: command)
        let accountFilter = args.string("account")
        let withCounts = args.bool("with-counts")

        var calendars = store.calendars(for: .event)
        if let filter = accountFilter {
            calendars = calendars.filter { $0.source.title.localizedCaseInsensitiveContains(filter) }
        }
        calendars.sort {
            $0.source.title == $1.source.title
                ? $0.title.localizedCompare($1.title) == .orderedAscending
                : $0.source.title.localizedCompare($1.source.title) == .orderedAscending
        }

        let payload = calendars.map { calendar -> [String: Any] in
            var entry: [String: Any] = [
                "id": calendar.calendarIdentifier,
                "title": calendar.title,
                "account": calendar.source.title,
                "writable": calendar.allowsContentModifications,
                "subscribed": calendar.isSubscribed,
            ]
            if withCounts {
                let now = Date()
                let start = Calendar.current.date(byAdding: .year, value: -1, to: now) ?? now
                let end = Calendar.current.date(byAdding: .year, value: 1, to: now) ?? now
                let predicate = store.predicateForEvents(withStart: start, end: end, calendars: [calendar])
                entry["event_count_last_and_next_year"] = store.events(matching: predicate).count
            }
            return entry
        }

        Out.success(command, ["count": payload.count, "calendars": payload])
    }

    // MARK: events

    private static func events(_ args: Args) -> Never {
        let command = "calendar events"
        let store = EventKitPermissions.authorizedStore(.event, command: command)

        let start: Date
        let end: Date
        if let rawStart = args.string("start") {
            start = DateParsing.require(rawStart, command: command, option: "start")
        } else {
            start = DateParsing.startOfToday()
        }
        if let rawEnd = args.string("end") {
            end = DateParsing.require(rawEnd, command: command, option: "end")
        } else {
            let days = args.int("days") ?? 1
            end = Calendar.current.date(byAdding: .day, value: days, to: start) ?? start
        }
        guard end > start else {
            Out.failure(command, BridgeError(
                code: "invalid_range",
                message: "--end must be after --start",
                hint: "Example: --start 2026-07-21 --days 7"
            ))
        }

        var calendars = store.calendars(for: .event)
        if let account = args.string("account") {
            calendars = calendars.filter { $0.source.title.localizedCaseInsensitiveContains(account) }
        }
        if let name = args.string("calendar") {
            calendars = calendars.filter { $0.title.localizedCaseInsensitiveContains(name) }
        }
        guard !calendars.isEmpty else {
            Out.failure(command, BridgeError(
                code: "no_matching_calendar",
                message: "No calendar matched the given --calendar/--account filters",
                hint: "Run `letta-privacy-bridge calendar list` to see available names."
            ))
        }

        let predicate = store.predicateForEvents(withStart: start, end: end, calendars: calendars)
        var found = store.events(matching: predicate)
        found.sort { ($0.startDate ?? .distantPast) < ($1.startDate ?? .distantPast) }
        if let limit = args.int("limit"), limit > 0, found.count > limit {
            found = Array(found.prefix(limit))
        }

        let payload = found.map { event -> [String: Any] in
            var entry: [String: Any] = [
                "id": event.eventIdentifier ?? "",
                "title": event.title ?? "",
                "all_day": event.isAllDay,
                "calendar": event.calendar?.title ?? "",
                "account": event.calendar?.source.title ?? "",
                "status": String(describing: event.status),
            ]
            if let startDate = event.startDate { entry["start"] = startDate.iso }
            if let endDate = event.endDate { entry["end"] = endDate.iso }
            if let location = event.location, !location.isEmpty { entry["location"] = location }
            if let url = event.url { entry["url"] = url.absoluteString }
            if let notes = event.notes, !notes.isEmpty { entry["notes"] = notes }
            return entry
        }

        Out.success(command, [
            "range": ["start": start.iso, "end": end.iso],
            "count": payload.count,
            "events": payload,
        ])
    }

    // MARK: create

    private static func createEvent(_ args: Args) -> Never {
        let command = "calendar create"
        let store = EventKitPermissions.authorizedStore(.event, command: command)

        let calendarName = args.require("calendar", command: command)
        let title = args.require("title", command: command)
        let allDay = args.bool("all-day")

        var candidates = store.calendars(for: .event).filter { $0.allowsContentModifications }
        if let account = args.string("account") {
            candidates = candidates.filter { $0.source.title.localizedCaseInsensitiveContains(account) }
        }
        let exact = candidates.first { $0.title.caseInsensitiveCompare(calendarName) == .orderedSame }
        let fuzzy = candidates.filter { $0.title.localizedCaseInsensitiveContains(calendarName) }
        guard let calendar = exact ?? (fuzzy.count == 1 ? fuzzy[0] : nil) else {
            Out.failure(command, BridgeError(
                code: fuzzy.isEmpty ? "no_matching_calendar" : "ambiguous_calendar",
                message: fuzzy.isEmpty
                    ? "No writable calendar named \"\(calendarName)\""
                    : "\"\(calendarName)\" matches \(fuzzy.count) calendars",
                hint: "Run `letta-privacy-bridge calendar list` and pass the exact title, " +
                      "optionally with --account."
            ))
        }

        let startRaw = args.string("date") ?? args.string("start")
        guard let startRaw else {
            Out.failure(command, BridgeError(
                code: "missing_argument",
                message: "Provide --start (timed event) or --date (all-day event)",
                hint: "Example: --start \"2026-07-22 10:00\" --duration 45"
            ))
        }
        let start = DateParsing.require(startRaw, command: command, option: "start")

        let end: Date
        if let rawEnd = args.string("end") {
            end = DateParsing.require(rawEnd, command: command, option: "end")
        } else if let minutes = args.int("duration") {
            end = start.addingTimeInterval(TimeInterval(minutes * 60))
        } else if allDay {
            end = start
        } else {
            end = start.addingTimeInterval(3600)
        }
        guard allDay || end > start else {
            Out.failure(command, BridgeError(
                code: "invalid_range",
                message: "Event end must be after its start",
                hint: "Use --end or --duration <minutes>."
            ))
        }

        let event = EKEvent(eventStore: store)
        event.calendar = calendar
        event.title = title
        event.isAllDay = allDay
        event.startDate = start
        event.endDate = end
        if let location = args.string("location") { event.location = location }
        if let notes = args.string("notes") { event.notes = notes }
        if let urlString = args.string("url"), let url = URL(string: urlString) { event.url = url }

        do {
            try store.save(event, span: .thisEvent, commit: true)
        } catch {
            Out.failure(command, BridgeError(
                code: "save_failed",
                message: "Calendar rejected the event: \(error.localizedDescription)",
                hint: "Confirm the calendar is writable (`calendar list` reports `writable`)."
            ))
        }

        Out.success(command, ["event": [
            "id": event.eventIdentifier ?? "",
            "title": event.title ?? "",
            "calendar": calendar.title,
            "account": calendar.source.title,
            "start": start.iso,
            "end": end.iso,
            "all_day": allDay,
        ]])
    }
}
