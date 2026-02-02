#!/bin/bash
# ==============================================================================
# get-hn-top-stories.sh - Get top stories from Hacker News using Safari
# ==============================================================================
# Description:
#   Opens Safari, navigates to news.ycombinator.com, and extracts the top
#   stories with their scores, age, and URLs.
#
# Prerequisites:
#   Safari must have "Allow JavaScript from Apple Events" enabled:
#   Safari > Settings > Advanced > Show Develop menu
#   Then: Develop > Allow JavaScript from Apple Events
#
# Usage:
#   ./get-hn-top-stories.sh
#   ./get-hn-top-stories.sh --count 10
#
# Options:
#   --count <n>    Number of stories to retrieve (default: 5, max: 30)
#
# Example:
#   ./get-hn-top-stories.sh --count 10
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Try to source common.sh if it exists
if [[ -f "$SCRIPT_DIR/../lib/common.sh" ]]; then
    source "$SCRIPT_DIR/../lib/common.sh"
else
    # Minimal error function if common.sh not available
    error_exit() { echo "Error: $1" >&2; exit 1; }
fi

# Default values
COUNT=5

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --count)
            COUNT="$2"
            shift 2
            ;;
        -h|--help)
            head -30 "$0" | tail -25
            exit 0
            ;;
        *)
            error_exit "Unknown option: $1"
            ;;
    esac
done

# Validate count
if ! [[ "$COUNT" =~ ^[0-9]+$ ]] || [[ "$COUNT" -lt 1 ]] || [[ "$COUNT" -gt 30 ]]; then
    error_exit "Count must be a number between 1 and 30"
fi

# Run the AppleScript with embedded JavaScript
osascript -e '
on run argv
    set storyCount to item 1 of argv as integer

    tell application "Safari"
        activate

        -- Open Hacker News
        if (count of windows) is 0 then
            make new document with properties {URL:"https://news.ycombinator.com"}
        else
            set URL of current tab of front window to "https://news.ycombinator.com"
        end if

        -- Wait for page to load
        set maxAttempts to 20
        set attemptCount to 0
        repeat
            delay 0.5
            set attemptCount to attemptCount + 1
            try
                set readyState to do JavaScript "document.readyState" in current tab of front window
                if readyState is "complete" then exit repeat
            on error errMsg
                if errMsg contains "Allow JavaScript from Apple Events" then
                    return "Error: JavaScript from Apple Events is not enabled in Safari.

To enable it:
1. Open Safari
2. Go to Safari > Settings > Advanced
3. Check \"Show Develop menu in menu bar\"
4. Close Settings
5. Go to Develop menu > Allow JavaScript from Apple Events

Then run this script again."
                end if
            end try
            if attemptCount >= maxAttempts then
                return "Error: Page failed to load within timeout"
            end if
        end repeat

        -- Small additional delay to ensure DOM is fully ready
        delay 0.5

        -- Extract stories using JavaScript
        set jsCode to "
            (function() {
                const count = " & storyCount & ";
                const stories = [];
                const rows = document.querySelectorAll(\"tr.athing\");

                for (let i = 0; i < Math.min(count, rows.length); i++) {
                    const row = rows[i];
                    const titleLine = row.querySelector(\"td.title span.titleline\");
                    const titleLink = titleLine ? titleLine.querySelector(\"a\") : null;
                    const title = titleLink ? titleLink.textContent : \"No title\";
                    const url = titleLink ? titleLink.href : \"\";

                    const sitebit = titleLine ? titleLine.querySelector(\"span.sitebit a\") : null;
                    const site = sitebit ? sitebit.textContent : \"\";

                    const subtext = row.nextElementSibling;
                    const scoreEl = subtext ? subtext.querySelector(\"span.score\") : null;
                    const score = scoreEl ? scoreEl.textContent : \"0 points\";

                    const ageEl = subtext ? subtext.querySelector(\"span.age a\") : null;
                    const age = ageEl ? ageEl.textContent : \"\";

                    let line = (i+1) + \". \" + title;
                    if (site) line += \" (\" + site + \")\";
                    line += \"\\n   \" + score + \" | \" + age;
                    line += \"\\n   \" + url;

                    stories.push(line);
                }
                return stories.join(\"\\n\\n\");
            })();
        "

        try
            set result to do JavaScript jsCode in current tab of front window
            set output to "=== HACKER NEWS TOP " & storyCount & " ===" & linefeed & linefeed & result

            -- Close the tab we opened (with small delay to ensure data is captured)
            delay 0.3
            close current tab of front window

            return output
        on error errMsg
            return "Error extracting stories: " & errMsg
        end try
    end tell
end run
' -- "$COUNT"
