// ==============================================================================
// ReminderCommands.swift - EventKit reminder lists, reads, creation, completion.
// ==============================================================================

import EventKit
import Foundation

enum ReminderCommands {
    static func run(_ args: Args) -> Never {
        let sub = args.positional(1) ?? "help"
        switch sub {
        case "lists", "list-lists": lists(args)
        case "list", "items": items(args)
        case "create": create(args)
        case "complete": complete(args)
        case "status": status()
        default:
            Out.failure("reminders", BridgeError(
                code: "unknown_subcommand",
                message: "Unknown reminders subcommand \"\(sub)\"",
                hint: "Available: lists, list, create, complete, status"
            ))
        }
    }

    private static func status() -> Never {
        Out.success("reminders status", [
            "authorization": EventKitPermissions.statusName(for: .reminder),
            "full_access": EventKitPermissions.hasFullAccess(.reminder),
        ])
    }

    /// EventKit reminder fetches are async; this collects them synchronously.
    private static func fetch(_ store: EKEventStore, predicate: NSPredicate) -> [EKReminder] {
        final class Box: @unchecked Sendable { var reminders: [EKReminder] = [] }
        let box = Box()
        let semaphore = DispatchSemaphore(value: 0)
        store.fetchReminders(matching: predicate) { result in
            box.reminders = result ?? []
            semaphore.signal()
        }
        semaphore.wait()
        return box.reminders
    }

    private static func lists(_ args: Args) -> Never {
        let command = "reminders lists"
        let store = EventKitPermissions.authorizedStore(.reminder, command: command)
        var calendars = store.calendars(for: .reminder)
        if let account = args.string("account") {
            calendars = calendars.filter { $0.source.title.localizedCaseInsensitiveContains(account) }
        }
        calendars.sort { $0.title.localizedCompare($1.title) == .orderedAscending }

        let payload = calendars.map { calendar -> [String: Any] in
            var entry: [String: Any] = [
                "id": calendar.calendarIdentifier,
                "title": calendar.title,
                "account": calendar.source.title,
                "writable": calendar.allowsContentModifications,
            ]
            if args.bool("with-counts") {
                let predicate = store.predicateForIncompleteReminders(
                    withDueDateStarting: nil, ending: nil, calendars: [calendar]
                )
                entry["open_count"] = fetch(store, predicate: predicate).count
            }
            return entry
        }
        Out.success(command, ["count": payload.count, "lists": payload])
    }

    private static func items(_ args: Args) -> Never {
        let command = "reminders list"
        let store = EventKitPermissions.authorizedStore(.reminder, command: command)

        var calendars = store.calendars(for: .reminder)
        if let account = args.string("account") {
            calendars = calendars.filter { $0.source.title.localizedCaseInsensitiveContains(account) }
        }
        if let name = args.string("list") {
            calendars = calendars.filter { $0.title.localizedCaseInsensitiveContains(name) }
            guard !calendars.isEmpty else {
                Out.failure(command, BridgeError(
                    code: "no_matching_list",
                    message: "No reminder list matched \"\(name)\"",
                    hint: "Run `letta-privacy-bridge reminders lists` for exact titles."
                ))
            }
        }

        let dueBefore = args.string("due-before").map {
            DateParsing.require($0, command: command, option: "due-before")
        }
        let dueAfter = args.string("due-after").map {
            DateParsing.require($0, command: command, option: "due-after")
        }
        let includeCompleted = args.bool("include-completed") || args.bool("completed-only")

        let predicate: NSPredicate = includeCompleted
            ? store.predicateForReminders(in: calendars)
            : store.predicateForIncompleteReminders(
                withDueDateStarting: dueAfter, ending: dueBefore, calendars: calendars
              )

        var reminders = fetch(store, predicate: predicate)
        if args.bool("completed-only") {
            reminders = reminders.filter(\.isCompleted)
        }
        if includeCompleted {
            if let dueBefore { reminders = reminders.filter { ($0.dueDateComponents?.date ?? .distantFuture) <= dueBefore } }
            if let dueAfter { reminders = reminders.filter { ($0.dueDateComponents?.date ?? .distantPast) >= dueAfter } }
        }
        reminders.sort {
            ($0.dueDateComponents?.date ?? .distantFuture) < ($1.dueDateComponents?.date ?? .distantFuture)
        }
        if let limit = args.int("limit"), limit > 0, reminders.count > limit {
            reminders = Array(reminders.prefix(limit))
        }

        let payload = reminders.map { reminder -> [String: Any] in
            var entry: [String: Any] = [
                "id": reminder.calendarItemIdentifier,
                "title": reminder.title ?? "",
                "list": reminder.calendar?.title ?? "",
                "account": reminder.calendar?.source.title ?? "",
                "completed": reminder.isCompleted,
                "priority": reminder.priority,
            ]
            if let due = reminder.dueDateComponents?.date { entry["due"] = due.iso }
            if let completion = reminder.completionDate { entry["completed_at"] = completion.iso }
            if let notes = reminder.notes, !notes.isEmpty { entry["notes"] = notes }
            return entry
        }

        Out.success(command, ["count": payload.count, "reminders": payload])
    }

    private static func create(_ args: Args) -> Never {
        let command = "reminders create"
        let store = EventKitPermissions.authorizedStore(.reminder, command: command)
        let title = args.require("title", command: command)

        let candidates = store.calendars(for: .reminder).filter(\.allowsContentModifications)
        let calendar: EKCalendar?
        if let name = args.string("list") {
            let exact = candidates.first { $0.title.caseInsensitiveCompare(name) == .orderedSame }
            let fuzzy = candidates.filter { $0.title.localizedCaseInsensitiveContains(name) }
            calendar = exact ?? (fuzzy.count == 1 ? fuzzy[0] : nil)
            guard calendar != nil else {
                Out.failure(command, BridgeError(
                    code: fuzzy.isEmpty ? "no_matching_list" : "ambiguous_list",
                    message: fuzzy.isEmpty
                        ? "No writable reminder list named \"\(name)\""
                        : "\"\(name)\" matches \(fuzzy.count) lists",
                    hint: "Run `letta-privacy-bridge reminders lists` and pass the exact title."
                ))
            }
        } else {
            calendar = store.defaultCalendarForNewReminders()
            guard calendar != nil else {
                Out.failure(command, BridgeError(
                    code: "no_default_list",
                    message: "Reminders has no default list configured",
                    hint: "Pass --list <title> explicitly."
                ))
            }
        }

        let reminder = EKReminder(eventStore: store)
        reminder.calendar = calendar
        reminder.title = title
        if let notes = args.string("notes") { reminder.notes = notes }
        if let priority = args.int("priority") { reminder.priority = max(0, min(9, priority)) }
        if let rawDue = args.string("due") {
            let due = DateParsing.require(rawDue, command: command, option: "due")
            reminder.dueDateComponents = Calendar.current.dateComponents(
                [.year, .month, .day, .hour, .minute], from: due
            )
        }

        do {
            try store.save(reminder, commit: true)
        } catch {
            Out.failure(command, BridgeError(
                code: "save_failed",
                message: "Reminders rejected the item: \(error.localizedDescription)",
                hint: "Confirm the list is writable (`reminders lists` reports `writable`)."
            ))
        }

        Out.success(command, ["reminder": [
            "id": reminder.calendarItemIdentifier,
            "title": reminder.title ?? "",
            "list": calendar?.title ?? "",
            "due": reminder.dueDateComponents?.date?.iso ?? "",
        ]])
    }

    private static func complete(_ args: Args) -> Never {
        let command = "reminders complete"
        let store = EventKitPermissions.authorizedStore(.reminder, command: command)
        let identifier = args.require("id", command: command)

        guard let reminder = store.calendarItem(withIdentifier: identifier) as? EKReminder else {
            Out.failure(command, BridgeError(
                code: "reminder_not_found",
                message: "No reminder with id \"\(identifier)\"",
                hint: "Ids come from `letta-privacy-bridge reminders list`."
            ))
        }
        reminder.isCompleted = true
        do {
            try store.save(reminder, commit: true)
        } catch {
            Out.failure(command, BridgeError(
                code: "save_failed",
                message: "Could not complete the reminder: \(error.localizedDescription)"
            ))
        }
        Out.success(command, ["reminder": [
            "id": reminder.calendarItemIdentifier,
            "title": reminder.title ?? "",
            "completed": true,
            "completed_at": reminder.completionDate?.iso ?? Date().iso,
        ]])
    }
}
