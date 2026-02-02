#!/bin/bash
# ==============================================================================
# google-search.sh - Perform a Google search using Safari
# ==============================================================================
# Description:
#   Opens Safari, performs a Google search, and extracts the top results
#   with their titles, URLs, and snippets.
#
# Prerequisites:
#   Safari must have "Allow JavaScript from Apple Events" enabled:
#   Safari > Settings > Advanced > Show Develop menu
#   Then: Develop > Allow JavaScript from Apple Events
#
# Usage:
#   ./google-search.sh "search query"
#   ./google-search.sh --count 10 "search query"
#
# Options:
#   --count <n>    Number of results to retrieve (default: 5, max: 20)
#
# Example:
#   ./google-search.sh "rust programming language"
#   ./google-search.sh --count 10 "best coffee shops NYC"
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Try to source common.sh if it exists
if [[ -f "$SCRIPT_DIR/../lib/common.sh" ]]; then
    source "$SCRIPT_DIR/../lib/common.sh"
else
    error_exit() { echo "Error: $1" >&2; exit 1; }
fi

# Default values
COUNT=5
QUERY=""

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
        -*)
            error_exit "Unknown option: $1"
            ;;
        *)
            QUERY="$1"
            shift
            ;;
    esac
done

# Validate inputs
[[ -z "$QUERY" ]] && error_exit "Search query is required"

if ! [[ "$COUNT" =~ ^[0-9]+$ ]] || [[ "$COUNT" -lt 1 ]] || [[ "$COUNT" -gt 20 ]]; then
    error_exit "Count must be a number between 1 and 20"
fi

# URL encode the query
ENCODED_QUERY=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$QUERY'''))")

# Run the AppleScript with embedded JavaScript
osascript -e '
on run argv
    set resultCount to item 1 of argv as integer
    set searchURL to item 2 of argv

    tell application "Safari"
        activate

        -- Open Google search
        if (count of windows) is 0 then
            make new document with properties {URL:searchURL}
        else
            set URL of current tab of front window to searchURL
        end if

        -- Wait for page to load
        set maxAttempts to 30
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

        -- Additional delay for dynamic content
        delay 1

        -- Extract search results using JavaScript
        set jsCode to "
            (function() {
                const maxResults = " & resultCount & ";
                const results = [];

                // Try multiple selector strategies as Google changes their DOM frequently
                let containers = document.querySelectorAll(\"div.tF2Cxc\");
                if (containers.length === 0) {
                    containers = document.querySelectorAll(\"div.g\");
                }

                let count = 0;
                for (const container of containers) {
                    if (count >= maxResults) break;

                    // Get title and URL
                    const titleEl = container.querySelector(\"h3\");
                    const linkEl = container.querySelector(\"a[href^=\\\"http\\\"]\");

                    if (!titleEl || !linkEl) continue;

                    const title = titleEl.textContent;
                    let url = linkEl.href;

                    // Skip Google internal links
                    if (url.includes(\"google.com/search\") || url.includes(\"accounts.google\")) continue;

                    // Clean up URL (remove Google text highlight fragments)
                    url = url.split(\"#:~:text=\")[0];

                    // Get snippet/description
                    const snippetEl = container.querySelector(\"div[data-sncf], div.VwiC3b, span.aCOpRe, div[style=\\\"-webkit-line-clamp:2\\\"]\");
                    let snippet = snippetEl ? snippetEl.textContent : \"\";
                    if (snippet.length > 200) snippet = snippet.substring(0, 200);

                    count++;
                    let line = count + \". \" + title + \"\\n   \" + url;
                    if (snippet) line += \"\\n   \" + snippet.trim();

                    results.push(line);
                }

                if (results.length === 0) {
                    return \"No results found. Google may have changed their page structure.\";
                }

                return results.join(\"\\n\\n\");
            })();
        "

        try
            set result to do JavaScript jsCode in current tab of front window
            set output to "=== GOOGLE SEARCH RESULTS ===" & linefeed & linefeed & result

            -- Close the tab we opened (with small delay to ensure data is captured)
            delay 0.3
            close current tab of front window

            return output
        on error errMsg
            return "Error extracting results: " & errMsg
        end try
    end tell
end run
' -- "$COUNT" "https://www.google.com/search?q=$ENCODED_QUERY"
