use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::sync::Mutex;

// State for managing the running service
pub struct ServiceState {
    pub running: bool,
}

impl Default for ServiceState {
    fn default() -> Self {
        Self { running: false }
    }
}

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
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PermissionsData {
    pub accessibility: bool,
    pub automation: std::collections::HashMap<String, bool>,
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

impl Default for OnboardingState {
    fn default() -> Self {
        let mut automation = std::collections::HashMap::new();
        automation.insert("Mail".to_string(), false);
        automation.insert("Calendar".to_string(), false);
        automation.insert("Reminders".to_string(), false);
        automation.insert("Notes".to_string(), false);
        automation.insert("Safari".to_string(), false);

        Self {
            version: 1,
            completed: false,
            current_step: "welcome".to_string(),
            data: OnboardingData {
                permissions: PermissionsData {
                    accessibility: false,
                    automation,
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

// Get service running state
#[tauri::command]
fn get_service_state(state: tauri::State<'_, Mutex<ServiceState>>) -> bool {
    state.lock().unwrap().running
}

// Set service running state
#[tauri::command]
fn set_service_running(running: bool, state: tauri::State<'_, Mutex<ServiceState>>) {
    state.lock().unwrap().running = running;
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_fs::init())
        .manage(Mutex::new(ServiceState::default()))
        .invoke_handler(tauri::generate_handler![
            read_onboarding_state,
            write_onboarding_state,
            read_config,
            write_config,
            open_system_preferences,
            check_accessibility_permission,
            get_service_state,
            set_service_running,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
