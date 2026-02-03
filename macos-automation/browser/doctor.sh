#!/bin/bash
# ==============================================================================
# doctor.sh - Check Safari browser automation prerequisites
# ==============================================================================
# Description:
#   Verifies that Safari is properly configured for browser automation.
#   Checks JavaScript from Apple Events permission and tests execution.
#
# Usage:
#   ./doctor.sh
#
# Output:
#   JSON with check results
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Safari Browser Automation Prerequisites Check"
echo "============================================="
echo ""

# Check 1: Safari is installed
echo -n "1. Safari installed: "
if [[ -d "/Applications/Safari.app" ]]; then
    echo "OK"
    SAFARI_OK=true
else
    echo "FAIL - Safari not found"
    SAFARI_OK=false
fi

# Check 2: ARIA snapshot library exists
echo -n "2. ARIA library exists: "
if [[ -f "$SCRIPT_DIR/lib/aria-snapshot.js" ]]; then
    echo "OK"
    LIB_OK=true
else
    echo "FAIL - aria-snapshot.js not found"
    LIB_OK=false
fi

# Check 3: Test JavaScript execution in Safari
echo -n "3. JavaScript from Apple Events: "
JS_RESULT=$(osascript -e '
tell application "Safari"
    activate
    if (count of windows) is 0 then
        make new document with properties {URL:"about:blank"}
    end if
    try
        set result to do JavaScript "1+1" in current tab of front window
        -- Result is a number (real), check if it equals 2
        if result is equal to 2 then
            return "OK"
        else
            return "FAIL - unexpected result: " & (result as string)
        end if
    on error errMsg
        if errMsg contains "Allow JavaScript from Apple Events" then
            return "FAIL - Not enabled. Go to Safari > Develop > Allow JavaScript from Apple Events"
        else
            return "FAIL - " & errMsg
        end if
    end try
end tell
' 2>&1)

if [[ "$JS_RESULT" == "OK" ]]; then
    echo "OK"
    JS_OK=true
else
    echo "$JS_RESULT"
    JS_OK=false
fi

# Check 4: Test ARIA library injection
echo -n "4. ARIA library injection: "
if [[ "$JS_OK" == "true" ]] && [[ "$LIB_OK" == "true" ]]; then
    INJECT_RESULT=$(osascript << EOF
set libPath to "$SCRIPT_DIR/lib/aria-snapshot.js"
tell application "Safari"
    try
        set ariaLib to read POSIX file libPath
        do JavaScript ariaLib in current tab of front window
        set hasFunc to do JavaScript "typeof window.__ariaSnapshot === 'function'" in current tab of front window
        if hasFunc is true then
            return "OK"
        else
            return "FAIL - Function not defined"
        end if
    on error errMsg
        return "FAIL - " & errMsg
    end try
end tell
EOF
)

    if [[ "$INJECT_RESULT" == "OK" ]]; then
        echo "OK"
        INJECT_OK=true
    else
        echo "$INJECT_RESULT"
        INJECT_OK=false
    fi
else
    echo "SKIP (depends on previous checks)"
    INJECT_OK=false
fi

# Check 5: Test snapshot generation
echo -n "5. Snapshot generation: "
if [[ "$INJECT_OK" == "true" ]]; then
    SNAP_RESULT=$(osascript -e '
    tell application "Safari"
        try
            set result to do JavaScript "JSON.stringify(window.__ariaSnapshot())" in current tab of front window
            if result contains "snapshot" then
                return "OK"
            else
                return "FAIL - Invalid result"
            end if
        on error errMsg
            return "FAIL - " & errMsg
        end try
    end tell
    ' 2>&1)

    if [[ "$SNAP_RESULT" == "OK" ]]; then
        echo "OK"
        SNAP_OK=true
    else
        echo "$SNAP_RESULT"
        SNAP_OK=false
    fi
else
    echo "SKIP (depends on previous checks)"
    SNAP_OK=false
fi

echo ""
echo "============================================="

# Summary
ALL_OK=true
if [[ "$SAFARI_OK" != "true" ]] || [[ "$LIB_OK" != "true" ]] || [[ "$JS_OK" != "true" ]]; then
    ALL_OK=false
fi

if [[ "$ALL_OK" == "true" ]]; then
    echo "All checks passed! Safari browser automation is ready."
    echo ""
    echo "Output JSON:"
    echo "{\"success\": true, \"safari\": true, \"library\": true, \"javascript\": true, \"injection\": $INJECT_OK, \"snapshot\": $SNAP_OK}"
else
    echo "Some checks failed. Please fix the issues above."
    echo ""
    if [[ "$JS_OK" != "true" ]]; then
        echo "To enable JavaScript from Apple Events:"
        echo "  1. Open Safari"
        echo "  2. Go to Safari > Settings > Advanced"
        echo "  3. Check 'Show Develop menu in menu bar'"
        echo "  4. Close Settings"
        echo "  5. Go to Develop > Allow JavaScript from Apple Events"
    fi
    echo ""
    echo "Output JSON:"
    echo "{\"success\": false, \"safari\": $SAFARI_OK, \"library\": $LIB_OK, \"javascript\": $JS_OK, \"injection\": $INJECT_OK, \"snapshot\": $SNAP_OK}"
fi
