# Development

## Run the bundled CLI from Terminal

If you installed the `.dmg` app, it includes a `son` CLI binary inside the app bundle. You can run it directly without `pip install`.

Typical path:

```bash
"/Applications/Son of Simon.app/Contents/MacOS/son" doctor
```

If that path doesn't exist, find it:

```bash
APP="/Applications/Son of Simon.app"
find "$APP/Contents" -maxdepth 4 -type f -name "son" -print
```

Convenience alias:

```bash
alias son="/Applications/Son of Simon.app/Contents/MacOS/son"
```

**Note:** when running from Terminal/iTerm, macOS Automation permission prompts apply to that terminal app.

## Run from source

If you want to run Son of Simon from this repository:

```bash
pip install -e .
son onboard
son run "Check my emails and summarize urgent ones"
```

### CLI commands

| Command | Description |
|---------|-------------|
| `son run "<goal>"` | Run a natural language goal |
| `son chat` | Interactive chat mode |
| `son start` | Start background service (heartbeat + Telegram + cron) |
| `son doctor` | Verify setup and permissions |

### Development setup

```bash
pip install -e ".[dev]"          # Install with dev dependencies
pytest                           # Run all tests
ruff check src/                  # Lint
mypy src/                        # Type check
```

### Building

```bash
./scripts/build-sidecar.sh       # Build PyInstaller binary
./scripts/build-app.sh           # Full build (sidecar + Tauri)
./scripts/release.sh patch       # Bump version, tag, push
```
