#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod python_manager;

use python_manager::PythonManager;
use std::sync::Mutex;
use tauri::{Manager, State};
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

            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                // Cleanup Python on window close
                let state = window.state::<AppState>();
                let mut python = state.python.lock().unwrap();
                python.cleanup();
            }
        })
        .invoke_handler(tauri::generate_handler![get_health, restart_python])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
