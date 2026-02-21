use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use tauri::RunEvent;

// Onboarding state structure
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OnboardingState {
    pub version: u32,
    pub completed: bool,
    pub current_step: String,
    pub data: OnboardingData,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OnboardingData {
    pub permissions: PermissionsData,
    pub api_key: ApiKeyData,
    pub telegram: TelegramData,
    #[serde(default)]
    pub dev_tools: DevToolsData,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PermissionsData {
    pub accessibility: bool,
    pub automation: std::collections::HashMap<String, bool>,
    #[serde(default)]
    pub folder_access: std::collections::HashMap<String, bool>,
    #[serde(default)]
    pub full_disk_access: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ApiKeyData {
    pub provider: String,
    pub configured: bool,
    pub verified: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TelegramData {
    pub configured: bool,
    pub skipped: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DevToolInfo {
    pub installed: bool,
    pub version: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NpxInfo {
    pub installed: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DevToolsData {
    pub homebrew: DevToolInfo,
    pub python: DevToolInfo,
    pub node: DevToolInfo,
    pub npx: NpxInfo,
    pub skipped: bool,
}

impl Default for DevToolsData {
    fn default() -> Self {
        Self {
            homebrew: DevToolInfo { installed: false, version: String::new() },
            python: DevToolInfo { installed: false, version: String::new() },
            node: DevToolInfo { installed: false, version: String::new() },
            npx: NpxInfo { installed: false },
            skipped: false,
        }
    }
}

impl Default for OnboardingState {
    fn default() -> Self {
        let mut automation = std::collections::HashMap::new();
        automation.insert("Mail".to_string(), false);
        automation.insert("Calendar".to_string(), false);
        automation.insert("Reminders".to_string(), false);
        automation.insert("Notes".to_string(), false);
        automation.insert("Safari".to_string(), false);
        automation.insert("Things3".to_string(), false);

        let mut folder_access = std::collections::HashMap::new();
        folder_access.insert("Documents".to_string(), false);
        folder_access.insert("Downloads".to_string(), false);
        folder_access.insert("Desktop".to_string(), false);

        Self {
            version: 1,
            completed: false,
            current_step: "welcome".to_string(),
            data: OnboardingData {
                permissions: PermissionsData {
                    accessibility: false,
                    automation,
                    folder_access,
                    full_disk_access: false,
                },
                api_key: ApiKeyData {
                    provider: "openai".to_string(),
                    configured: false,
                    verified: false,
                },
                telegram: TelegramData {
                    configured: false,
                    skipped: false,
                },
                dev_tools: DevToolsData::default(),
            },
        }
    }
}

fn get_macbot_dir() -> Result<PathBuf, String> {
    dirs::home_dir()
        .map(|p| p.join(".macbot"))
        .ok_or_else(|| "Could not find home directory".to_string())
}

fn get_onboarding_path() -> Result<PathBuf, String> {
    get_macbot_dir().map(|p| p.join("onboarding.json"))
}

fn get_env_path() -> Result<PathBuf, String> {
    get_macbot_dir().map(|p| p.join(".env"))
}

fn get_pid_path() -> Result<PathBuf, String> {
    get_macbot_dir().map(|p| p.join("service.pid"))
}

/// Stop the service if running by reading PID file and killing the process
fn stop_service_if_running() {
    if let Ok(pid_path) = get_pid_path() {
        if pid_path.exists() {
            if let Ok(pid_str) = std::fs::read_to_string(&pid_path) {
                if let Ok(pid) = pid_str.trim().parse::<i32>() {
                    // Try to kill the process
                    let _ = std::process::Command::new("kill")
                        .arg(pid.to_string())
                        .output();
                    // Remove the PID file
                    let _ = std::fs::remove_file(&pid_path);
                }
            }
        }
    }
}

// Read onboarding state from disk
#[tauri::command]
fn read_onboarding_state() -> Result<OnboardingState, String> {
    let path = get_onboarding_path()?;
    if path.exists() {
        let content = std::fs::read_to_string(&path).map_err(|e| e.to_string())?;
        serde_json::from_str(&content).map_err(|e| e.to_string())
    } else {
        Ok(OnboardingState::default())
    }
}

// Write onboarding state to disk
#[tauri::command]
fn write_onboarding_state(state: OnboardingState) -> Result<(), String> {
    let path = get_onboarding_path()?;
    // Ensure directory exists
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let content = serde_json::to_string_pretty(&state).map_err(|e| e.to_string())?;
    std::fs::write(&path, content).map_err(|e| e.to_string())
}

// Read .env config file
#[tauri::command]
fn read_config() -> Result<String, String> {
    let path = get_env_path()?;
    if path.exists() {
        std::fs::read_to_string(&path).map_err(|e| e.to_string())
    } else {
        Ok(String::new())
    }
}

// Write .env config file
#[tauri::command]
fn write_config(content: String) -> Result<(), String> {
    let path = get_env_path()?;
    // Ensure directory exists
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    std::fs::write(&path, content).map_err(|e| e.to_string())
}

// Open System Preferences to a specific pane
#[tauri::command]
fn open_system_preferences(pane: String) -> Result<(), String> {
    std::process::Command::new("open")
        .arg(format!("x-apple.systempreferences:{}", pane))
        .spawn()
        .map_err(|e| e.to_string())?;
    Ok(())
}

// Check if we can read common user folders (TCC-protected)
#[tauri::command]
fn check_folder_access() -> std::collections::HashMap<String, bool> {
    let mut results = std::collections::HashMap::new();
    if let Some(home) = dirs::home_dir() {
        for folder in &["Documents", "Downloads", "Desktop"] {
            let path = home.join(folder);
            let accessible = std::fs::read_dir(&path).is_ok();
            results.insert(folder.to_string(), accessible);
        }
    }
    results
}

// Check if Full Disk Access is granted by trying to read ~/Library/Messages/chat.db
#[tauri::command]
fn check_full_disk_access() -> bool {
    if let Some(home) = dirs::home_dir() {
        let chat_db = home.join("Library/Messages/chat.db");
        chat_db.exists() && std::fs::metadata(&chat_db).is_ok()
    } else {
        false
    }
}

// Check if accessibility permission is granted for THIS app
#[tauri::command]
fn check_accessibility_permission() -> bool {
    #[cfg(target_os = "macos")]
    {
        macos_accessibility_client::accessibility::application_is_trusted()
    }
    #[cfg(not(target_os = "macos"))]
    {
        true // Non-macOS platforms don't need this check
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_fs::init())
        .invoke_handler(tauri::generate_handler![
            read_onboarding_state,
            write_onboarding_state,
            read_config,
            write_config,
            open_system_preferences,
            check_accessibility_permission,
            check_folder_access,
            check_full_disk_access,
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|_app_handle, event| {
            if let RunEvent::Exit = event {
                // Stop the service when the app exits
                stop_service_if_running();
            }
        });
}
