#!/bin/bash
# ==============================================================================
# get-today-events.sh - Get all events scheduled for today
# ==============================================================================
# Description:
#   Retrieves all calendar events for today across all calendars or a specific
#   calendar. Shows event time, title, location, and calendar name.
#
# Usage:
#   ./get-today-events.sh
#   ./get-today-events.sh --calendar "Work"
#
# Options:
#   --calendar <name>   Only show events from the specified calendar
#
# Output:
#   A chronologically sorted list of today's events
#
# Example:
#   ./get-today-events.sh
#   ./get-today-events.sh --calendar "Personal"
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

# Default values
CALENDAR_NAME=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --calendar)
            CALENDAR_NAME="$2"
            shift 2
            ;;
        -h|--help)
            head -28 "$0" | tail -23
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
    let startOfDay = calendar.startOfDay(for: now)
    let endOfDay = calendar.date(byAdding: .day, value: 1, to: startOfDay)!

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

    let predicate = store.predicateForEvents(withStart: startOfDay, end: endOfDay, calendars: calendars)
    let events = store.events(matching: predicate).sorted { $0.startDate < $1.startDate }

    if events.isEmpty {
        if calendarFilter.isEmpty {
            print("No events scheduled for today.")
        } else {
            print("No events scheduled for today in \"\(calendarFilter)\".")
        }
        return
    }

    if calendarFilter.isEmpty {
        print("=== TODAYS EVENTS ===\n")
    } else {
        print("=== TODAYS EVENTS: \(calendarFilter) ===\n")
    }

    // Group events by calendar
    var eventsByCalendar: [String: [EKEvent]] = [:]
    for event in events {
        let calName = event.calendar.title
        if eventsByCalendar[calName] == nil {
            eventsByCalendar[calName] = []
        }
        eventsByCalendar[calName]!.append(event)
    }

    let timeFormatter = DateFormatter()
    timeFormatter.dateFormat = "h:mm a"

    for (calName, calEvents) in eventsByCalendar.sorted(by: { $0.key < $1.key }) {
        print("\u{1F4C5} \(calName)")
        for event in calEvents {
            let timeStr: String
            if event.isAllDay {
                timeStr = "All Day"
            } else {
                timeStr = timeFormatter.string(from: event.startDate)
            }

            print("  \(timeStr) - \(event.title ?? "No title")")
            if let location = event.location, !location.isEmpty {
                print("           Location: \(location)")
            }
        }
        print("")
    }
}

semaphore.wait()
' 2>&1
