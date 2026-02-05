---
id: browser_automation
name: Browser Automation
description: Automate web interactions for bookings, form submissions, and purchases using ARIA-based Safari control.
apps:
  - Safari
tasks:
  - browser_navigate
  - browser_snapshot
  - browser_click
  - browser_type
  - browser_select
  - browser_scroll_to
  - browser_get_text
  - browser_execute_js
  - browser_screenshot
  - browser_close_tab
  - browser_dismiss_cookies
  - browser_wait
  - browser_press_key
  - browser_visual_snapshot
  - analyze_screenshot
examples:
  - "Book a table at Restaurant XYZ for Friday at 7pm"
  - "Make a reservation for 2 people tomorrow night"
  - "Buy tickets for the concert next week"
  - "Fill out the contact form on this page"
  - "Submit the inquiry form with my details"
safe_defaults:
  timeout: 20
  max_elements: 200
confirm_before_write:
  - submit form
  - complete purchase
  - confirm booking
requires_permissions:
  - Automation:Safari
  - Allow JavaScript from Apple Events
---

## Behavior Notes

### When to Use Browser Automation
Use browser_* tools for interactive web tasks:
- Making reservations or bookings
- Filling out and submitting forms
- Completing purchases
- Navigating multi-step workflows

For simple lookups (reading content, searching), use web_search and web_fetch instead.

### The ARIA Workflow
Browser automation uses semantic element references (e1, e2, etc.):

1. **Navigate**: `browser_navigate` to load the page
2. **Snapshot**: `browser_snapshot` to see interactive elements with refs
3. **Interact**: Use refs with `browser_click`, `browser_type`, `browser_select`
4. **Verify**: Take another snapshot to confirm changes

### Making Online Bookings/Reservations

When asked to book, reserve, or purchase something online, ALWAYS try to complete it.

**First, verify required info**: date, exact time, party size, name, contact. Ask if anything is missing or vague.

**Then proceed with the booking:**

1. **Find the website**: Use web_search to find the official site
2. **Quick recon**: Use web_fetch to quickly scan the page for booking options
3. **Switch to browser**: Use browser_navigate to go to the booking page
4. **Take a snapshot**: Use browser_snapshot to see elements with refs (e1, e2, etc.)
5. **Fill forms**: Use browser_type to enter details (name, date, time, party size, etc.)
6. **Click buttons**: Use browser_click to select options, proceed, submit
7. **Verify completion**: Take another snapshot to confirm the booking went through

### Key Insights

- **web_fetch first**: Great for quickly checking what's available
- **browser_* to interact**: Must continue with browser tools to fill forms and click buttons
- **Don't stop early**: The user asked to BOOK, not just find contact info

### Being Persistent

If one approach doesn't work, try alternatives:
- Look for "Reservierung", "Buchen", "Book", "Reserve" buttons/links
- Try contact forms if no booking system exists
- Fill out and submit inquiry forms on the user's behalf
- As a last resort, draft an email for the user to send

### Handling Common Issues

- **Cookie banners**: Use `browser_dismiss_cookies` to clear consent popups
- **Overlays/popups**: Use `browser_press_key` with "escape" to dismiss
- **Dynamic content**: Use `browser_wait` after clicks for AJAX to complete
- **Can't find element**: Try `browser_scroll_to` or take a new snapshot
- **Visual debugging**: Use `browser_visual_snapshot` + `analyze_screenshot` for complex pages

### Form Filling Best Practices

- Use `browser_type` with `clear=true` (default) to replace existing values
- For dropdowns, use `browser_select` with the option value
- Use `browser_type` with `submit=true` to press Enter after typing
- Always snapshot after major interactions to verify state
