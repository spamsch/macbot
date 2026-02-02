#!/bin/bash
# ==============================================================================
# get-week-events.sh - Get all events for the upcoming week
# ==============================================================================
# Description:
#   Retrieves all calendar events for the next 7 days (or custom range),
#   organized by day. Shows time, title, location, and calendar name.
#
# Usage:
#   ./get-week-events.sh
#   ./get-week-events.sh --days 14
#   ./get-week-events.sh --calendar "Work"
#
# Options:
#   --days <n>          Number of days to look ahead (default: 7)
#   --calendar <name>   Only show events from the specified calendar
#
# Example:
#   ./get-week-events.sh
#   ./get-week-events.sh --days 30 --calendar "Personal"
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

# Default values
DAYS=7
CALENDAR_NAME=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --days)
            DAYS="$2"
            shift 2
            ;;
        --calendar)
            CALENDAR_NAME="$2"
            shift 2
            ;;
        -h|--help)
            head -26 "$0" | tail -21
            exit 0
            ;;
        *)
            error_exit "Unknown option: $1"
            ;;
    esac
done

# Use Swift with EventKit for efficient date-based queries
swift -e '
import EventKit
import Foundation

let daysAhead = '"$DAYS"'
let calendarFilter = "'"$CALENDAR_NAME"'"
let store = EKEventStore()
let semaphore = DispatchSemaphore(value: 0)

store.requestFullAccessToEvents { granted, error in
    defer { semaphore.signal() }

    guard granted else {
        print("Error: Calendar access denied. Please grant access in System Settings > Privacy & Security > Calendars.")
        return
    }

    let calendar = Calendar.current
    let now = Date()
    let startDate = calendar.startOfDay(for: now)
    let endDate = calendar.date(byAdding: .day, value: daysAhead, to: startDate)!

    // Filter calendars if specified
    var calendars: [EKCalendar]? = nil
    if !calendarFilter.isEmpty {
        let allCalendars = store.calendars(for: .event)
        let matchingCalendars = allCalendars.filter { $0.title == calendarFilter }
        if matchingCalendars.isEmpty {
            print("Error: Calendar \"\(calendarFilter)\" not found.")
            return
        }
        calendars = matchingCalendars
    }

    let predicate = store.predicateForEvents(withStart: startDate, end: endDate, calendars: calendars)
    let events = store.events(matching: predicate).sorted { $0.startDate < $1.startDate }

    if events.isEmpty {
        print("No events scheduled for the next \(daysAhead) days.")
        return
    }

    print("=== NEXT \(daysAhead) DAYS ===\n")

    // Group events by day, then by calendar
    let dayFormatter = DateFormatter()
    dayFormatter.dateFormat = "EEEE, MMMM d"

    let timeFormatter = DateFormatter()
    timeFormatter.dateFormat = "h:mm a"

    var eventsByDay: [String: [EKEvent]] = [:]
    var dayOrder: [String] = []

    for event in events {
        let dayKey = dayFormatter.string(from: event.startDate)
        if eventsByDay[dayKey] == nil {
            eventsByDay[dayKey] = []
            dayOrder.append(dayKey)
        }
        eventsByDay[dayKey]!.append(event)
    }

    for dayKey in dayOrder {
        print("\u{1F4C6} \(dayKey)")

        guard let dayEvents = eventsByDay[dayKey] else { continue }

        // Group by calendar within each day
        var eventsByCalendar: [String: [EKEvent]] = [:]
        for event in dayEvents {
            let calName = event.calendar.title
            if eventsByCalendar[calName] == nil {
                eventsByCalendar[calName] = []
            }
            eventsByCalendar[calName]!.append(event)
        }

        for (calName, calEvents) in eventsByCalendar.sorted(by: { $0.key < $1.key }) {
            print("  \u{1F4C5} \(calName)")
            for event in calEvents {
                let timeStr: String
                if event.isAllDay {
                    timeStr = "All Day"
                } else {
                    timeStr = timeFormatter.string(from: event.startDate)
                }

                print("    \(timeStr) - \(event.title ?? "No title")")
                if let location = event.location, !location.isEmpty {
                    print("             Location: \(location)")
                }
            }
        }
        print("")
    }
}

semaphore.wait()
' 2>&1
