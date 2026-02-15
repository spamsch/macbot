---
id: system_controls
name: System Controls
description: Control WiFi, Bluetooth, volume, dark mode, and Do Not Disturb.
apps:
  - System Settings
tasks:
  - get_system_status
  - toggle_wifi
  - toggle_bluetooth
  - list_bluetooth_devices
  - set_volume
  - toggle_dark_mode
  - toggle_dnd
essential_tasks:
  - get_system_status
examples:
  - "Turn off WiFi"
  - "Set volume to 50%"
  - "Enable dark mode"
  - "What's my system status?"
  - "Turn on Do Not Disturb"
  - "Show connected Bluetooth devices"
  - "Mute the volume"
safe_defaults: {}
confirm_before_write:
  - toggle wifi off
  - toggle bluetooth off
requires_permissions:
  - Automation:System Events
---

## Behavior Notes

### System Status
- Use `get_system_status` to check current state before making changes.
- Reports: WiFi (on/off + network name), Bluetooth (on/off), volume (% + muted), dark mode, DND.

### Toggle Pattern
- All toggle tasks accept `--on`, `--off`, or no args (toggle).
- **Check current state first** — toggles are idempotent. If WiFi is already on and user says "turn on WiFi", report that it's already on rather than toggling.
- Confirm before turning **off** WiFi or Bluetooth (may disconnect the user).

### WiFi
- Auto-detects the WiFi hardware device via `networksetup -listallhardwareports`.
- Shows current network name when WiFi is on.

### Bluetooth
- Uses IOBluetooth framework via JavaScript for Automation (no third-party deps).
- Falls back to `blueutil` if ASObjC approach fails.
- `list_bluetooth_devices` shows paired devices with connection status.
- **Cannot programmatically connect/disconnect specific Bluetooth devices** — only toggle the adapter on/off.

### Volume
- Level range: 0-100.
- Can set level, mute, or unmute independently or together.
- "Mute" keeps the volume level but silences output; "unmute" restores it.

### Dark Mode
- Toggles macOS system-wide dark/light appearance.
- Requires Automation permission for System Events.

### Do Not Disturb
- Uses a Shortcuts bridge — requires a shortcut named "Toggle Do Not Disturb".
- If the shortcut doesn't exist, the script outputs setup instructions.
- Guide the user to create the shortcut if needed:
  1. Open Shortcuts.app
  2. Create a new shortcut named "Toggle Do Not Disturb"
  3. Add the "Set Focus" action → select "Do Not Disturb" → set to "Toggle"
  4. Save

### Common Request Patterns
- **"Turn off WiFi"** → confirm → `toggle_wifi(state="off")`
- **"Set volume to 50"** → `set_volume(level=50)`
- **"Mute"** → `set_volume(mute=true)`
- **"Dark mode on"** → `toggle_dark_mode(state="on")`
- **"What's connected?"** → `list_bluetooth_devices(connected_only=true)`
- **"Status check"** → `get_system_status()`
