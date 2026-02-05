---
id: safari_assistant
name: Safari Assistant
description: Control Safari tabs, open URLs, and perform web searches.
apps:
  - Safari
tasks:
  - open_url_in_safari
  - list_safari_tabs
  - get_current_safari_page
  - extract_safari_links
  - web_search
  - web_fetch
examples:
  - "Open GitHub in Safari"
  - "Show me my open tabs"
  - "Close all tabs except the current one"
  - "Search the web for Python tutorials"
  - "Read the content of this webpage"
safe_defaults:
  new_tab: true
  timeout: 30
confirm_before_write:
  - close all tabs
requires_permissions:
  - Automation:Safari
---

## Behavior Notes

### Opening URLs
- Open in a new tab by default
- Accept partial URLs (add https:// if missing)
- For common sites, use the correct URL (e.g., "github" -> github.com)

### Tab Management
- List tabs with their titles and URLs
- When closing tabs, confirm if closing multiple
- Never close all tabs without explicit confirmation

### Web Search vs Fetch
**For simple lookups** (finding information, reading content):
- `web_search` - Quick DuckDuckGo search, returns titles/URLs/snippets
- `web_fetch` - Fetch a URL and extract readable text content

**For interactive tasks** (bookings, form submissions, purchases):
Use the Browser Automation skill with browser_* tools instead.

### Common Request Patterns
- **"search the web for..." or "look up..."** → web_search (fast, no browser needed)
- **"read this webpage" or "fetch this URL"** → web_fetch (extracts text from URL)
- **"open X in Safari"** → open_url_in_safari with the URL
- **"what tabs do I have open?"** → list_safari_tabs
