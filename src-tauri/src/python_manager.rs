use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};
use std::thread;
use tauri::{AppHandle, Emitter};

pub struct PythonManager {
    port: u16,
    process: Option<Child>,
    heartbeat_failures: u32,
    last_heartbeat: Option<Instant>,
    is_healthy: bool,
}

impl PythonManager {
    pub fn new(port: u16) -> Self {
        Self {
            port,
            process: None,
            heartbeat_failures: 0,
            last_heartbeat: None,
            is_healthy: false,
        }
    }

    pub fn port(&self) -> u16 {
        self.port
    }

    pub fn is_running(&self) -> bool {
        self.process.is_some()
    }

    pub fn is_healthy(&self) -> bool {
        self.is_healthy
    }

    pub fn start(&mut self) -> Result<(), Box<dyn std::error::Error>> {
        // Kill existing process if any
        self.cleanup();

        // Start Python backend
        let python_path = self.get_python_path();
        let script_path = self.get_script_path();

        let mut cmd = Command::new(&python_path);
        cmd.arg(&script_path)
            .arg("--port")
            .arg(self.port.to_string())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());

        // Hide console window on Windows
        #[cfg(target_os = "windows")]
        {
            use std::os::windows::process::CommandExt;
            cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
        }

        let child = cmd.spawn()
            .map_err(|e| format!("Failed to start Python: {}", e))?;

        self.process = Some(child);
        self.is_healthy = true;

        // Wait for health endpoint to be ready
        self.wait_for_ready(Duration::from_secs(30))?;

        Ok(())
    }

    pub fn restart(&mut self) -> Result<(), Box<dyn std::error::Error>> {
        self.cleanup();
        thread::sleep(Duration::from_secs(2));
        self.start()
    }

    pub fn cleanup(&mut self) {
        if let Some(mut process) = self.process.take() {
            // Try graceful shutdown first
            let _ = process.kill();
            let _ = process.wait();
        }
        self.is_healthy = false;
        self.heartbeat_failures = 0;
    }

    pub fn start_heartbeat(&mut self, app_handle: AppHandle) {
        let port = self.port;
        let url = format!("http://localhost:{}/health", port);

        thread::spawn(move || {
            let client = reqwest::blocking::Client::new();
            let mut failures = 0u32;

            loop {
                thread::sleep(Duration::from_secs(5));

                match client.get(&url).timeout(Duration::from_secs(3)).send() {
                    Ok(resp) if resp.status().is_success() => {
                        failures = 0;
                        let _ = app_handle.emit("python-heartbeat", true);
                    }
                    _ => {
                        failures += 1;
                        let _ = app_handle.emit("python-heartbeat", false);

                        if failures >= 3 {
                            let _ = app_handle.emit("python-crashed", ());
                            // Wait for restart
                            thread::sleep(Duration::from_secs(10));
                            failures = 0;
                        }
                    }
                }
            }
        });
    }

    fn wait_for_ready(&self, timeout: Duration) -> Result<(), Box<dyn std::error::Error>> {
        let start = Instant::now();
        let url = format!("http://localhost:{}/health", self.port);
        let client = reqwest::blocking::Client::new();

        while start.elapsed() < timeout {
            match client.get(&url).timeout(Duration::from_secs(2)).send() {
                Ok(resp) if resp.status().is_success() => {
                    return Ok(());
                }
                _ => {
                    thread::sleep(Duration::from_millis(500));
                }
            }
        }

        Err("Python backend failed to start within timeout".into())
    }

    fn get_python_path(&self) -> String {
        // In production, this points to the embedded Python
        // In development, use system Python
        if cfg!(debug_assertions) {
            if cfg!(target_os = "windows") {
                // Use pythonw.exe (no console window) instead of python.exe
                let local_app_data = std::env::var("LOCALAPPDATA").unwrap_or_default();
                let pythonw_path = format!("{}\\Programs\\Python\\Python314\\pythonw.exe", local_app_data);
                let python_path = format!("{}\\Programs\\Python\\Python314\\python.exe", local_app_data);
                // Prefer pythonw.exe (no console), fall back to python.exe
                if std::path::Path::new(&pythonw_path).exists() {
                    pythonw_path
                } else if std::path::Path::new(&python_path).exists() {
                    python_path
                } else {
                    "python".to_string()
                }
            } else {
                "python3".to_string()
            }
        } else {
            // Production: embedded Python in the app bundle
            let exe_dir = std::env::current_exe()
                .unwrap()
                .parent()
                .unwrap()
                .to_path_buf();

            if cfg!(target_os = "windows") {
                exe_dir.join("python-runtime").join("python.exe").to_string_lossy().to_string()
            } else {
                exe_dir.join("python-runtime").join("bin").join("python3").to_string_lossy().to_string()
            }
        }
    }

    fn get_script_path(&self) -> String {
        if cfg!(debug_assertions) {
            // Development: use the backend directory relative to the project root
            // The exe is in src-tauri/target/debug/, so go up 3 levels to reach project root
            let exe_dir = std::env::current_exe()
                .unwrap()
                .parent()
                .unwrap()
                .to_path_buf();
            let project_root = exe_dir.parent().unwrap().parent().unwrap().parent().unwrap();
            project_root.join("backend").join("main.py").to_string_lossy().to_string()
        } else {
            // Production: bundled with the app
            let exe_dir = std::env::current_exe()
                .unwrap()
                .parent()
                .unwrap()
                .to_path_buf();

            exe_dir.join("engine").join("main.py").to_string_lossy().to_string()
        }
    }
}

impl Drop for PythonManager {
    fn drop(&mut self) {
        self.cleanup();
    }
}
