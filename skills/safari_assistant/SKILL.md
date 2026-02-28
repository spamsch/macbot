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
  - get_hacker_news
essential_tasks:
  - open_url_in_safari
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

### Act First, Ask Later
When the user asks you to do something in Safari, **just do it**. Do not ask clarifying questions like "are you logged in?" or "which tab?". Assume the user is logged in and wants you to proceed immediately. Open the URL, navigate the page, and report what you find. If something fails (not logged in, page won't load), handle it then — don't pre-screen.

### Opening URLs
- Open in a new tab by default
- Accept partial URLs (add https:// if missing)
- For common sites, use the correct URL (e.g., "github" -> github.com, "reddit" -> reddit.com)

### Tab Management
- List tabs with their titles and URLs
- When closing tabs, confirm if closing multiple
- Never close all tabs without explicit confirmation

### Automatic Fallback to Browser Automation
If `open_url_in_safari`, `get_current_safari_page`, or `extract_safari_links` fail (e.g., JavaScript blocked, page not readable, empty results), **immediately switch to browser automation tools without asking the user**:

1. Use `browser_navigate` to load the page
2. Use `browser_snapshot` to read the page content and interactive elements
3. Use `browser_click`, `browser_type`, etc. to interact

Do NOT tell the user to enable settings or change Safari preferences. Just switch tools and keep going.

### Web Search vs Fetch
**For simple lookups** (finding information, reading content):
- `web_search` - Quick DuckDuckGo search, returns titles/URLs/snippets
- `web_fetch` - Fetch a URL and extract readable text content

**For interactive tasks** (bookings, form submissions, purchases):
Use the Browser Automation skill with browser_* tools instead.

### Common Request Patterns
- **"check my notifications on X"** → open the notifications page directly, read it, report back
- **"search the web for..." or "look up..."** → web_search (fast, no browser needed)
- **"read this webpage" or "fetch this URL"** → web_fetch (extracts text from URL)
- **"open X in Safari"** → open_url_in_safari with the URL
- **"what tabs do I have open?"** → list_safari_tabs
