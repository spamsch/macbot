---
id: data_app_creator
name: Data App Creator
description: Create self-contained HTML apps from user data (CSV, JSON, bank statements, APIs) with interactive tables and charts.
apps: []
tasks:
  - write_file
  - read_file
  - run_shell_command
  - get_preferences
  - spotlight_search
  - web_fetch
  - fetch_url
  - web_search
essential_tasks: []
examples:
  - "Create a dashboard from my bank statement CSV"
  - "Build an app to explore this spending data"
  - "Make a visualization of my tax export"
  - "Create a weather dashboard using a public API"
  - "Build a data viewer for this CSV file"
  - "Create an interactive chart from this data"
safe_defaults:
  embed_data: true
  auto_open: true
confirm_before_write:
  - embed sensitive financial data
  - embed API keys in client-side code
requires_permissions: []
---

## Behavior Notes

### When to Use This Skill

Use this skill when the user wants a **persistent, visual app** they can open and interact with in a browser. Examples: dashboards, data explorers, chart viewers, interactive tables.

**Do NOT use this skill** when the user just wants quick analysis or a one-off answer ("what's my average spending?"). For that, use Python or shell commands directly and report the result.

**Rule of thumb:** If the user says "create", "build", "make", "dashboard", or "app" — use this skill. If they say "analyze", "tell me", "what is" — just answer the question.

### The App Creation Workflow

1. **Understand** what the user wants to see — ask for clarification if the request is vague
2. **Locate data** — use `spotlight_search` to find files, `read_file` to load them, or `web_fetch`/`fetch_url` for API data
3. **Analyze structure** — peek at the first 5–10 rows, detect column names, types, and value ranges
4. **Choose app type** — dashboard, table viewer, chart, or API-driven (see Common App Types below)
5. **Generate HTML** — a single self-contained HTML file following the structure template below
6. **Save** to the `apps` well-known directory under a descriptive subfolder: `<apps-dir>/<descriptive-name>/index.html`
7. **Open** in Safari with `open -a Safari <path>`

Always use `get_preferences` to resolve the `apps` directory path — never hardcode `~/Documents/Apps`.

### App Directory Convention

Each app lives in its own subfolder under the `apps` well-known directory:

```
~/Documents/Apps/
  bank-statement-2024/
    index.html
  weather-dashboard/
    index.html
    data.json        (only for large datasets)
```

- **Kebab-case** folder names — descriptive, no generic names like "dashboard"
- **Always `index.html`** as the entry point
- One app per folder — keeps things tidy for the user

### Data Processing Patterns

**CSV files** — embed as a JS string constant, parse client-side with PapaParse:
```html
<script src="https://cdn.jsdelivr.net/npm/papaparse@5/papaparse.min.js"></script>
<script>
const csvData = `...embedded CSV...`;
const parsed = Papa.parse(csvData, { header: true, dynamicTyping: true });
</script>
```

**JSON files** — embed directly as a JS object literal:
```html
<script>
const data = [ ...embedded JSON... ];
</script>
```

**API data** — use client-side `fetch()` with loading states and error handling:
```html
<script>
async function loadData() {
  showLoading();
  try {
    const res = await fetch('https://api.example.com/data');
    const data = await res.json();
    renderDashboard(data);
  } catch (err) {
    showError('Failed to load data. Check your connection and try again.');
  }
}
</script>
```

**Large data (>500KB)** — save as a separate `data.json` in the same folder, fetch it via a relative path:
```html
<script>
fetch('data.json').then(r => r.json()).then(renderDashboard);
</script>
```

### HTML Structure Template

Every generated app should follow this base skeleton:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>App Title</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", system-ui, sans-serif;
      background: #f5f5f7;
      color: #1d1d1f;
      padding: 24px;
      line-height: 1.5;
    }
    @media (prefers-color-scheme: dark) {
      body { background: #1d1d1f; color: #f5f5f7; }
      .card { background: #2c2c2e; }
    }
    h1 { font-size: 28px; font-weight: 700; margin-bottom: 24px; }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }
    .card {
      background: #fff;
      border-radius: 12px;
      padding: 20px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    }
    .card h2 { font-size: 14px; color: #86868b; font-weight: 500; margin-bottom: 4px; }
    .card .value { font-size: 32px; font-weight: 700; }
    table { width: 100%; border-collapse: collapse; }
    th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid #e5e5ea; }
    th { font-weight: 600; font-size: 13px; color: #86868b; text-transform: uppercase; letter-spacing: 0.5px; }
    @media (prefers-color-scheme: dark) {
      th, td { border-color: #3a3a3c; }
    }
  </style>
</head>
<body>
  <h1>App Title</h1>
  <div class="grid">
    <!-- Summary cards -->
  </div>
  <!-- Charts -->
  <!-- Detail table -->
  <script>
    // Data and rendering logic
  </script>
</body>
</html>
```

**Layout pattern:** Summary cards at top → charts in the middle → detail table at the bottom.

### Recommended Libraries

Load from CDN — keeps apps self-contained with no build step:

- **Chart.js** — default choice for line, bar, pie, and doughnut charts. Simple API, looks good out of the box.
  ```html
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
  ```
- **PapaParse** — CSV parsing. Always use `header: true` and `dynamicTyping: true`.
  ```html
  <script src="https://cdn.jsdelivr.net/npm/papaparse@5/papaparse.min.js"></script>
  ```
- **Plotly.js** — use only when the user needs advanced interactivity (3D charts, hover details, range sliders). Heavier than Chart.js.
  ```html
  <script src="https://cdn.jsdelivr.net/npm/plotly.js@2/dist/plotly.min.js"></script>
  ```
- **Vanilla JS tables** — for simple data with <100 rows, skip libraries entirely. Add sort/filter with plain JS event handlers.

### Common App Types

**Financial dashboard** (bank statements, expense exports):
- Auto-detect date, amount, and description/category columns
- Summary cards: total income, total expenses, net, transaction count
- Chart: spending over time (grouped by month or week)
- Chart: spending by category (pie or bar)
- Table: all transactions, sortable by date/amount
- Format amounts with currency symbols and 2 decimal places

**Generic CSV explorer** (any tabular data):
- Sortable, filterable table with all columns
- Column statistics at top: count, min, max, mean for numeric columns
- Search/filter input above the table
- Handle missing values gracefully — show "—" not "null"

**API dashboard** (weather, stocks, public APIs):
- Loading spinner while fetching
- Auto-refresh with configurable interval (default: 5 minutes)
- Error state with retry button
- Last-updated timestamp in the header
- Use `fetch()` with timeout handling

**Health data viewer** (Apple Health exports, fitness data):
- Time-series line charts with date range controls
- Summary stats per period (daily, weekly, monthly)
- Multiple metrics on the same chart where it makes sense

### Styling Defaults

- **Font:** `-apple-system, BlinkMacSystemFont, "SF Pro Text", system-ui, sans-serif`
- **Spacing:** multiples of 8px (8, 16, 24, 32)
- **Colors:** light background `#f5f5f7`, white cards `#fff`, dark text `#1d1d1f`, muted labels `#86868b`
- **Dark mode:** always include `@media (prefers-color-scheme: dark)` with inverted backgrounds and lighter text
- **Responsive:** use `grid-template-columns: repeat(auto-fit, minmax(280px, 1fr))` for card layouts
- **Border radius:** 12px for cards, 8px for inputs/buttons
- **Shadows:** subtle `box-shadow: 0 1px 3px rgba(0,0,0,0.08)` on cards

### Smart Data Detection

Use these heuristics to pick the right visualization automatically:

- **Date column + number column** → line chart (time series)
- **Category column + number column** → bar chart or pie chart
- **Financial keywords** in filename or headers (amount, balance, debit, credit, transaction) → financial dashboard layout
- **All text columns** → searchable/sortable table, no charts
- **Lat/lng columns** → mention map possibility but stick to table (maps need Leaflet, which adds complexity)
- **Multiple numeric columns** → summary stats cards + comparison bar chart

### Security & Privacy

- **Confirm before embedding** account numbers, SSNs, or other PII in the HTML file
- **Redact sensitive fields** to last-4 digits when displaying (e.g., `****1234`)
- **Warn the user** that HTML files store data in plain text — anyone with file access can read them
- **Never embed API keys** in client-side code — use public/free-tier APIs or prompt the user to enter keys at runtime
- **Sanitize data** before injecting into HTML to prevent XSS (escape `<`, `>`, `&`, `"`, `'` in user data strings)
