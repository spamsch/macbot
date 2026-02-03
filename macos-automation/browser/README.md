# Safari Browser Automation

ARIA-based browser automation for Safari using AppleScript and JavaScript.

## Overview

This module provides browser automation capabilities inspired by [OpenClaw](https://github.com/openclaw/openclaw)'s approach, but adapted for Safari on macOS. Instead of using CSS selectors (which break frequently), it uses ARIA (Accessible Rich Internet Applications) roles to identify and interact with elements.

## How It Works

1. **Navigate** to a page (`navigate.sh`) - injects the ARIA library
2. **Snapshot** the page (`snapshot.sh`) - extracts interactive elements with refs like `e1`, `e2`
3. **Interact** using refs (`click.sh`, `type.sh`, etc.)
4. **Repeat** - take new snapshot after UI changes

## Prerequisites

Safari must have JavaScript from Apple Events enabled:

1. Open Safari
2. Go to **Safari > Settings > Advanced**
3. Check **"Show Develop menu in menu bar"**
4. Close Settings
5. Go to **Develop > Allow JavaScript from Apple Events**

Run `./doctor.sh` to verify setup.

## Scripts

| Script | Description |
|--------|-------------|
| `navigate.sh` | Navigate to URL, inject ARIA library |
| `snapshot.sh` | Get ARIA snapshot with element refs |
| `click.sh` | Click element by ref |
| `type.sh` | Type text into input by ref |
| `select.sh` | Select dropdown option by ref |
| `scroll.sh` | Scroll element into view |
| `get-text.sh` | Get text content of element |
| `screenshot.sh` | Capture screenshot |
| `close-tab.sh` | Close current tab |
| `doctor.sh` | Check prerequisites |

## Usage Example

```bash
# 1. Navigate to a page
./navigate.sh "https://www.google.com"

# 2. Get snapshot of interactive elements
./snapshot.sh
# Output:
# [e1] textbox "Search"
# [e2] button "Google Search"
# [e3] button "I'm Feeling Lucky"

# 3. Type into search box
./type.sh e1 "weather in berlin"

# 4. Click search button
./click.sh e2

# 5. Get new snapshot (page changed)
./snapshot.sh
# Output: (search results page)
# [e1] link "Weather in Berlin - Google Search"
# ...

# 6. Close tab when done
./close-tab.sh
```

## Snapshot Output Format

```
[e1] button "Search"
[e2] textbox "Email" value="user@example.com"
[e3] link "Sign up"
  [e4] heading "Welcome"
[e5] combobox "Country" value="Germany"
[e6] checkbox "Remember me" value="unchecked"
```

Each line shows:
- **Ref ID**: `[e1]` - use this to interact with the element
- **Role**: `button`, `textbox`, `link`, `combobox`, etc.
- **Name**: The accessible name (label, text content, etc.)
- **Value**: Current value for inputs (optional)
- **Attributes**: `[disabled]`, `[required]`, etc. (if applicable)

## ARIA Roles

The library focuses on interactive elements:

| Role | Elements |
|------|----------|
| `button` | `<button>`, `<input type="submit">` |
| `link` | `<a href="...">` |
| `textbox` | `<input type="text">`, `<textarea>` |
| `checkbox` | `<input type="checkbox">` |
| `radio` | `<input type="radio">` |
| `combobox` | `<select>` |
| `searchbox` | `<input type="search">` |
| `slider` | `<input type="range">` |
| `heading` | `<h1>` - `<h6>` |

## JSON Output

All scripts output JSON for easy parsing:

```json
{
  "success": true,
  "snapshot": "[e1] button \"Search\"\n[e2] textbox \"Query\"",
  "refs": {
    "e1": {"role": "button", "name": "Search", "interactive": true},
    "e2": {"role": "textbox", "name": "Query", "value": "", "interactive": true}
  },
  "url": "https://example.com",
  "title": "Example Page",
  "stats": {
    "totalElements": 2,
    "interactiveElements": 2
  }
}
```

## Integration with macbot

These scripts are wrapped by Python tasks in `src/macbot/tasks/browser_automation.py` for use with the macbot agent:

```python
# Agent can use these tools:
await browser_navigate(url="https://booking.com")
snapshot = await browser_snapshot()
await browser_type(ref="e1", text="Berlin")
await browser_click(ref="e2")
```

## Troubleshooting

### "JavaScript from Apple Events not enabled"
Enable it in Safari's Develop menu (see Prerequisites above).

### "ARIA library not loaded"
Run `navigate.sh` first, or use `snapshot.sh --inject`.

### "Element eX not found"
The page has changed since the last snapshot. Run `snapshot.sh` again.

### Elements not appearing in snapshot
By default, only interactive elements are included. Use `snapshot.sh --all` to include all elements.

## Architecture

```
┌────────────────────────────────────────┐
│           Shell Scripts                │
│  navigate.sh, snapshot.sh, click.sh    │
└────────────────────────────────────────┘
                    │
                    ▼
┌────────────────────────────────────────┐
│           AppleScript                  │
│   Controls Safari, executes JavaScript │
└────────────────────────────────────────┘
                    │
                    ▼
┌────────────────────────────────────────┐
│       aria-snapshot.js                 │
│   Extracts ARIA tree, manages refs     │
└────────────────────────────────────────┘
                    │
                    ▼
┌────────────────────────────────────────┐
│           Safari DOM                   │
│   The actual web page                  │
└────────────────────────────────────────┘
```

## Files

```
macos-automation/browser/
├── README.md           # This file
├── lib/
│   └── aria-snapshot.js  # Core JavaScript library
├── navigate.sh         # Navigate to URL
├── snapshot.sh         # Get ARIA snapshot
├── click.sh            # Click element
├── type.sh             # Type text
├── select.sh           # Select option
├── scroll.sh           # Scroll to element
├── get-text.sh         # Get element text
├── screenshot.sh       # Take screenshot
├── close-tab.sh        # Close tab
└── doctor.sh           # Check prerequisites
```
