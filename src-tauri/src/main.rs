#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod python_manager;

use python_manager::PythonManager;
use std::fs;
use std::path::PathBuf;
use std::process::Command;
use std::sync::Mutex;
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Emitter, Manager, State,
};
use serde::{Deserialize, Serialize};

struct AppState {
    python: Mutex<PythonManager>,
}

#[derive(Serialize, Deserialize)]
struct HealthStatus {
    status: String,
    python_running: bool,
    port: u16,
}

// ========== Health ==========

#[tauri::command]
fn get_health(state: State<AppState>) -> HealthStatus {
    let python = state.python.lock().unwrap();
    HealthStatus {
        status: if python.is_healthy() { "ok".to_string() } else { "error".to_string() },
        python_running: python.is_running(),
        port: python.port(),
    }
}

#[tauri::command]
fn restart_python(state: State<AppState>) -> Result<String, String> {
    let mut python = state.python.lock().unwrap();
    python.restart().map_err(|e| e.to_string())?;
    Ok("Python restarted".to_string())
}

// ========== Config Management ==========

fn get_config_dir() -> PathBuf {
    let home = dirs::home_dir().unwrap_or_else(|| PathBuf::from("."));
    home.join(".omnicouncil")
}

fn get_config_path() -> PathBuf {
    get_config_dir().join("config.json")
}

#[tauri::command]
fn read_config() -> Result<String, String> {
    let path = get_config_path();
    if path.exists() {
        fs::read_to_string(&path).map_err(|e| format!("Failed to read config: {}", e))
    } else {
        Ok("{}".to_string())
    }
}

#[tauri::command]
fn write_config(content: String) -> Result<(), String> {
    let dir = get_config_dir();
    fs::create_dir_all(&dir).map_err(|e| format!("Failed to create config dir: {}", e))?;
    let path = get_config_path();
    fs::write(&path, content).map_err(|e| format!("Failed to write config: {}", e))
}

// ========== Chrome Launch ==========

#[tauri::command]
fn launch_chrome_debug() -> Result<String, String> {
    #[cfg(target_os = "windows")]
    {
        Command::new("cmd")
            .args(["/C", "start", "chrome", "--remote-debugging-port=9222"])
            .spawn()
            .map_err(|e| format!("Failed to launch Chrome: {}", e))?;
    }

    #[cfg(target_os = "macos")]
    {
        Command::new("open")
            .args(["-a", "Google Chrome", "--args", "--remote-debugging-port=9222"])
            .spawn()
            .map_err(|e| format!("Failed to launch Chrome: {}", e))?;
    }

    #[cfg(target_os = "linux")]
    {
        Command::new("google-chrome")
            .arg("--remote-debugging-port=9222")
            .spawn()
            .map_err(|e| format!("Failed to launch Chrome: {}", e))?;
    }

    Ok("Chrome launched with debug port 9222".to_string())
}

#[tauri::command]
fn check_chrome_connection() -> Result<bool, String> {
    match std::net::TcpStream::connect_timeout(
        &"127.0.0.1:9222".parse().unwrap(),
        std::time::Duration::from_secs(2),
    ) {
        Ok(_) => Ok(true),
        Err(_) => Ok(false),
    }
}

// ========== Main ==========

fn main() {
    tauri::Builder::default()
        .manage(AppState {
            python: Mutex::new(PythonManager::new(8765)),
        })
        .setup(|app| {
            let state = app.state::<AppState>();
            let mut python = state.python.lock().unwrap();

            // Start Python backend
            python.start().expect("Failed to start Python backend");

            // Start heartbeat monitor
            let app_handle = app.handle().clone();
            python.start_heartbeat(app_handle);

            // ========== System Tray ==========
            let show_item = MenuItem::with_id(app, "show", "显示主窗口", true, None::<&str>)?;
            let settings_item = MenuItem::with_id(app, "settings", "设置", true, None::<&str>)?;
            let restart_item = MenuItem::with_id(app, "restart", "重启服务", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "退出", true, None::<&str>)?;

            let menu = Menu::with_items(
                app,
                &[&show_item, &settings_item, &restart_item, &quit_item],
            )?;

            let _tray = TrayIconBuilder::new()
                .icon(app.default_window_icon().unwrap().clone())
                .menu(&menu)
                .tooltip("OmniCouncil")
                .on_menu_event(move |app, event| {
                    match event.id.as_ref() {
                        "show" => {
                            if let Some(window) = app.get_webview_window("main") {
                                let _ = window.show();
                                let _ = window.set_focus();
                            }
                        }
                        "settings" => {
                            if let Some(window) = app.get_webview_window("main") {
                                let _ = window.show();
                                let _ = window.set_focus();
                                let _ = window.emit("open-settings", ());
                            }
                        }
                        "restart" => {
                            let state = app.state::<AppState>();
                            let mut python = state.python.lock().unwrap();
                            let _ = python.restart();
                        }
                        "quit" => {
                            let state = app.state::<AppState>();
                            let mut python = state.python.lock().unwrap();
                            python.cleanup();
                            app.exit(0);
                        }
                        _ => {}
                    }
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                })
                .build(app)?;

            Ok(())
        })
        .on_window_event(|window, event| {
            // Hide to tray instead of closing
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                // Prevent default close, hide to tray instead
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .invoke_handler(tauri::generate_handler![
            get_health,
            restart_python,
            read_config,
            write_config,
            launch_chrome_debug,
            check_chrome_connection
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
