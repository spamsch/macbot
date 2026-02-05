# Tauri GUI Implementation Plan

## Overview

Transform Son of Simon from a CLI-only tool into a user-friendly desktop application using Tauri. The app will feature a beautiful onboarding experience and a dashboard that displays the service output.

## Goals

1. **Zero technical knowledge required** - No Python, no terminal, no manual permission granting
2. **Beautiful onboarding** - Guide users through setup with a polished UI
3. **Resumable setup** - Users can quit and resume onboarding where they left off
4. **Live service dashboard** - Show `son start` output in real-time after onboarding

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Tauri App (~20MB)                       │
│  ┌─────────────────────┐    ┌─────────────────────────────┐ │
│  │   Svelte Frontend   │◄──►│   Rust Backend (minimal)    │ │
│  │   + Tailwind CSS    │IPC │   - Sidecar management      │ │
│  │                     │    │   - Config I/O              │ │
│  └─────────────────────┘    └──────────────┬──────────────┘ │
└────────────────────────────────────────────┼────────────────┘
                                             │ spawns
                              ┌──────────────▼──────────────┐
                              │   Python Sidecar (~80MB)    │
                              │   (PyInstaller bundle)      │
                              │   Contains: son CLI         │
                              └─────────────────────────────┘
```

## Tech Stack

| Component | Technology | Rationale |
|-----------|------------|-----------|
| Framework | Tauri 2.x | Small bundle, native performance |
| Frontend | Svelte 5 | Minimal boilerplate, small bundle |
| Styling | Tailwind CSS | Rapid UI development |
| Icons | Lucide Svelte | Clean, consistent iconography |
| Animations | Svelte transitions + CSS | Smooth onboarding experience |
| Python bundling | PyInstaller | Creates standalone executable |
| Rust code | Minimal (~150 LOC) | Just IPC commands |

## Project Structure

```
macbot/
├── src/macbot/                    # Existing Python (unchanged)
├── macos-automation/              # Existing AppleScripts (unchanged)
├── pyproject.toml                 # Existing
│
├── app/                           # NEW: Tauri application
│   ├── src-tauri/
│   │   ├── src/
│   │   │   ├── main.rs            # Tauri entry point
│   │   │   └── lib.rs             # IPC commands
│   │   ├── binaries/              # PyInstaller output goes here
│   │   │   └── .gitkeep
│   │   ├── icons/                 # App icons (all sizes)
│   │   ├── Cargo.toml
│   │   └── tauri.conf.json
│   │
│   ├── src/
│   │   ├── main.ts                # Svelte entry
│   │   ├── App.svelte             # Root component
│   │   ├── app.css                # Global styles + Tailwind
│   │   │
│   │   ├── lib/
│   │   │   ├── stores/
│   │   │   │   ├── onboarding.ts  # Onboarding state
│   │   │   │   └── service.ts     # Service state
│   │   │   ├── components/
│   │   │   │   ├── ui/            # Reusable UI components
│   │   │   │   │   ├── Button.svelte
│   │   │   │   │   ├── Input.svelte
│   │   │   │   │   ├── Card.svelte
│   │   │   │   │   ├── Progress.svelte
│   │   │   │   │   └── LogViewer.svelte
│   │   │   │   └── onboarding/
│   │   │   │       ├── StepIndicator.svelte
│   │   │   │       ├── WelcomeStep.svelte
│   │   │   │       ├── PermissionsStep.svelte
│   │   │   │       ├── ApiKeyStep.svelte
│   │   │   │       ├── TelegramStep.svelte
│   │   │   │       └── CompleteStep.svelte
│   │   │   └── utils/
│   │   │       ├── tauri.ts       # Tauri API wrappers
│   │   │       └── config.ts      # Config helpers
│   │   │
│   │   └── routes/
│   │       ├── Onboarding.svelte  # Onboarding wizard
│   │       ├── Dashboard.svelte   # Main dashboard
│   │       └── Settings.svelte    # Settings panel
│   │
│   ├── index.html
│   ├── package.json
│   ├── vite.config.ts
│   ├── svelte.config.js
│   ├── tailwind.config.js
│   └── tsconfig.json
│
├── scripts/
│   ├── build-sidecar.sh           # Build Python sidecar
│   ├── build-app.sh               # Build complete app
│   └── create-dmg.sh              # Create distributable DMG
│
└── docs/
    └── TAURI_GUI_PLAN.md          # This file
```

## Onboarding Flow

### State Management

```typescript
// ~/.macbot/onboarding.json
interface OnboardingState {
  version: 1;
  completed: boolean;
  currentStep: 'welcome' | 'permissions' | 'apikey' | 'telegram' | 'complete';
  data: {
    permissions: {
      accessibility: boolean;
      automation: Record<string, boolean>; // app name -> granted
    };
    apiKey: {
      provider: 'anthropic' | 'openai' | 'other';
      configured: boolean;
      verified: boolean;
    };
    telegram: {
      configured: boolean;
      skipped: boolean;
    };
  };
}
```

### Step 1: Welcome
- Animated logo/illustration
- Brief description of what Son of Simon does
- "Get Started" button
- No back button (first step)

### Step 2: Permissions
- Explain why permissions are needed
- List required permissions with status indicators:
  - Accessibility (required for automation)
  - Automation per-app (Mail, Calendar, Reminders, Notes, Safari)
- "Open System Settings" button for each
- Auto-detect when permissions are granted (poll every 2s)
- Can proceed with partial permissions (warn user)

### Step 3: API Key
- Provider selector dropdown (Anthropic recommended, OpenAI, Other/LiteLLM)
- API key input (password field with show/hide toggle)
- "Get an API key" link (opens provider's website)
- "Verify" button that makes a test API call
- Show success/error feedback
- Store in ~/.macbot/.env

### Step 4: Telegram (Optional)
- Clear skip option ("I'll set this up later")
- Step-by-step instructions with illustrations:
  1. Open Telegram, search @BotFather
  2. Send /newbot, follow prompts
  3. Copy the token
- Bot token input field
- "Get Chat ID" button that:
  - Starts bot temporarily
  - Instructs user to send a message
  - Captures chat ID automatically
- Verify connection works

### Step 5: Complete
- Success animation (confetti or checkmark)
- Summary of what was configured
- "Launch Dashboard" button
- Triggers transition to Dashboard + `son start`

## Dashboard

### Layout
```
┌─────────────────────────────────────────────────────────┐
│  Son of Simon                    ● Running    [⚙][─][×] │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌─────────────────────────────────────────────────────┐│
│  │ Service Output                              [Clear] ││
│  ├─────────────────────────────────────────────────────┤│
│  │ 14:23:01  Starting Son of Simon...                  ││
│  │ 14:23:02  ✓ Configuration loaded                    ││
│  │ 14:23:02  ✓ Cron service started (3 jobs)           ││
│  │ 14:23:02  ✓ Telegram bot connected                  ││
│  │ ...                                                 ││
│  │ █                                                   ││
│  └─────────────────────────────────────────────────────┘│
│                                                         │
│  ┌───────────┐ ┌───────────┐ ┌───────────┐             │
│  │ ⏹ Stop   │ │ 🔄 Restart│ │ ⚙ Settings│             │
│  └───────────┘ └───────────┘ └───────────┘             │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### Features
- Real-time log streaming from `son start` stdout/stderr
- Auto-scroll with "scroll to bottom" button when scrolled up
- Color-coded log levels (info, warning, error)
- Service status indicator (Running/Stopped/Error)
- Start/Stop/Restart buttons
- Settings button opens Settings panel
- Window close minimizes to background (optional menu bar icon)

## Rust Backend (src-tauri/src/lib.rs)

```rust
use tauri::Manager;
use std::sync::Mutex;
use tauri_plugin_shell::{ShellExt, process::CommandChild};

struct ServiceState {
    child: Option<CommandChild>,
}

#[tauri::command]
async fn start_service(
    app: tauri::AppHandle,
    state: tauri::State<'_, Mutex<ServiceState>>,
) -> Result<(), String> {
    let sidecar = app.shell().sidecar("son").unwrap();
    let (mut rx, child) = sidecar
        .args(["start", "--foreground"])
        .spawn()
        .map_err(|e| e.to_string())?;

    // Store child for later termination
    state.lock().unwrap().child = Some(child);

    // Stream output to frontend
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            if let tauri_plugin_shell::process::CommandEvent::Stdout(line) = event {
                app.emit("service-output", String::from_utf8_lossy(&line).to_string()).ok();
            }
        }
    });

    Ok(())
}

#[tauri::command]
async fn stop_service(state: tauri::State<'_, Mutex<ServiceState>>) -> Result<(), String> {
    if let Some(child) = state.lock().unwrap().child.take() {
        child.kill().map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
async fn run_doctor(app: tauri::AppHandle) -> Result<String, String> {
    let output = app.shell()
        .sidecar("son")
        .unwrap()
        .args(["doctor", "--json"])
        .output()
        .await
        .map_err(|e| e.to_string())?;

    Ok(String::from_utf8_lossy(&output.stdout).to_string())
}

#[tauri::command]
async fn verify_api_key(provider: String, key: String) -> Result<bool, String> {
    // Make a minimal API call to verify the key works
    // This could call the sidecar or make a direct HTTP request
    todo!()
}

#[tauri::command]
fn read_config() -> Result<String, String> {
    let config_path = dirs::home_dir()
        .ok_or("No home directory")?
        .join(".macbot/.env");
    std::fs::read_to_string(&config_path).map_err(|e| e.to_string())
}

#[tauri::command]
fn write_config(content: String) -> Result<(), String> {
    let config_path = dirs::home_dir()
        .ok_or("No home directory")?
        .join(".macbot/.env");
    std::fs::create_dir_all(config_path.parent().unwrap()).map_err(|e| e.to_string())?;
    std::fs::write(&config_path, content).map_err(|e| e.to_string())
}

#[tauri::command]
fn open_system_preferences(pane: String) -> Result<(), String> {
    std::process::Command::new("open")
        .arg(format!("x-apple.systempreferences:{}", pane))
        .spawn()
        .map_err(|e| e.to_string())?;
    Ok(())
}
```

## Implementation Tasks

### Phase 1: Project Setup (Foundation)
- [ ] 1.1 Initialize Tauri project in `app/` directory
- [ ] 1.2 Configure Svelte 5 + TypeScript + Vite
- [ ] 1.3 Set up Tailwind CSS with custom theme
- [ ] 1.4 Create base UI components (Button, Input, Card)
- [ ] 1.5 Set up app icons and metadata
- [ ] 1.6 Configure sidecar in tauri.conf.json

### Phase 2: Python Sidecar
- [ ] 2.1 Create PyInstaller spec file
- [ ] 2.2 Add `--foreground` flag to `son start` (no daemon mode)
- [ ] 2.3 Add `--json` flag to `son doctor` for machine-readable output
- [ ] 2.4 Build script for sidecar (`scripts/build-sidecar.sh`)
- [ ] 2.5 Test sidecar execution from Tauri

### Phase 3: Onboarding UI
- [ ] 3.1 Create onboarding state store with persistence
- [ ] 3.2 Implement step indicator component
- [ ] 3.3 Implement Welcome step with animations
- [ ] 3.4 Implement Permissions step with auto-detection
- [ ] 3.5 Implement API Key step with verification
- [ ] 3.6 Implement Telegram step (optional flow)
- [ ] 3.7 Implement Complete step with transition
- [ ] 3.8 Add step navigation (back/continue)
- [ ] 3.9 Test resume functionality

### Phase 4: Dashboard
- [ ] 4.1 Implement log viewer component with auto-scroll
- [ ] 4.2 Implement service status indicator
- [ ] 4.3 Wire up Start/Stop/Restart buttons
- [ ] 4.4 Stream service output to UI
- [ ] 4.5 Implement Settings panel
- [ ] 4.6 Handle window close (minimize vs quit)

### Phase 5: Rust Backend
- [ ] 5.1 Implement start_service command with streaming
- [ ] 5.2 Implement stop_service command
- [ ] 5.3 Implement run_doctor command
- [ ] 5.4 Implement config read/write commands
- [ ] 5.5 Implement open_system_preferences command
- [ ] 5.6 Implement verify_api_key command

### Phase 6: Build & Distribution
- [ ] 6.1 Create universal binary build script (arm64 + x86_64)
- [ ] 6.2 Configure code signing (optional, for Gatekeeper)
- [ ] 6.3 Create DMG with drag-to-install layout
- [ ] 6.4 Set up GitHub Actions for automated builds
- [ ] 6.5 Create GitHub Release workflow
- [ ] 6.6 Test installation on clean macOS system

### Phase 7: Polish
- [ ] 7.1 Add loading states and error handling
- [ ] 7.2 Add keyboard shortcuts
- [ ] 7.3 Add menu bar icon (optional, minimize to tray)
- [ ] 7.4 Add auto-update functionality (Tauri updater)
- [ ] 7.5 Performance optimization
- [ ] 7.6 Accessibility audit (VoiceOver support)

## CLI Modifications Required

### New flags for `son start`:
```
--foreground    Run in foreground (don't daemonize), stream logs to stdout
```

### New flags for `son doctor`:
```
--json          Output results as JSON for programmatic parsing
```

### Example `son doctor --json` output:
```json
{
  "python_version": "3.12.0",
  "permissions": {
    "accessibility": true,
    "automation": {
      "Mail": true,
      "Calendar": true,
      "Reminders": false,
      "Notes": true,
      "Safari": true
    }
  },
  "config": {
    "api_key_configured": true,
    "telegram_configured": false,
    "model": "anthropic/claude-sonnet-4-20250514"
  },
  "macos_version": "14.0",
  "all_ok": false,
  "issues": ["Reminders automation not granted"]
}
```

## Design Tokens

```css
/* Colors */
--color-primary: #6366f1;      /* Indigo */
--color-primary-hover: #4f46e5;
--color-success: #22c55e;       /* Green */
--color-warning: #f59e0b;       /* Amber */
--color-error: #ef4444;         /* Red */
--color-bg: #0f172a;            /* Slate 900 */
--color-bg-card: #1e293b;       /* Slate 800 */
--color-text: #f8fafc;          /* Slate 50 */
--color-text-muted: #94a3b8;    /* Slate 400 */

/* Spacing */
--spacing-page: 2rem;
--spacing-card: 1.5rem;

/* Border radius */
--radius-sm: 0.375rem;
--radius-md: 0.5rem;
--radius-lg: 0.75rem;

/* Shadows */
--shadow-card: 0 4px 6px -1px rgb(0 0 0 / 0.3);
```

## Timeline Estimate

| Phase | Estimated Effort |
|-------|------------------|
| Phase 1: Project Setup | Foundation work |
| Phase 2: Python Sidecar | Small changes |
| Phase 3: Onboarding UI | Main UI work |
| Phase 4: Dashboard | Core feature |
| Phase 5: Rust Backend | Integration |
| Phase 6: Build & Distribution | DevOps |
| Phase 7: Polish | Final touches |

## Open Questions

1. **Menu bar icon?** Should the app have a menu bar presence when minimized?
2. **Auto-launch on login?** Should we offer this option in settings?
3. **Update mechanism?** Tauri has built-in updater - should we use it?
4. **Telemetry?** Any anonymous usage tracking for debugging?

## Success Criteria

- [ ] User can download DMG and install without terminal
- [ ] Onboarding completes in < 5 minutes for new users
- [ ] Service starts automatically after onboarding
- [ ] Logs are visible and readable in dashboard
- [ ] App bundle size < 150MB total
- [ ] Works on macOS 12+ (Monterey and later)
