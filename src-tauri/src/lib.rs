use serde::{Deserialize, Serialize};
use std::env;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Seek, SeekFrom};
use std::net::UdpSocket;
#[cfg(unix)]
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, ExitStatus, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager, State};

#[derive(Default)]
struct ServiceRuntime {
    child: Option<Child>,
    server_mode: bool,
    last_error: Option<String>,
    log_path: Option<PathBuf>,
}

struct ServiceManager(Mutex<ServiceRuntime>);
struct AppConfigState(AppConfig);

struct ServiceLaunch {
    command: Command,
    log_path: Option<PathBuf>,
}

#[derive(Debug, PartialEq, Eq)]
enum ServiceLaunchRuntime {
    BundledPython(PathBuf),
    Uv(PathBuf),
}

#[cfg(unix)]
unsafe extern "C" {
    fn killpg(pgrp: i32, sig: i32) -> i32;
}

#[cfg(unix)]
const SIGKILL: i32 = 9;

#[derive(Clone, Debug, Deserialize)]
#[serde(default)]
struct AppConfig {
    service: ServiceConfig,
    desktop: DesktopConfig,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(default)]
struct ServiceConfig {
    host: String,
    port: u16,
    engine: String,
    default_voice: String,
    default_rate: f32,
    default_format: String,
    max_input_length: usize,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(default)]
struct DesktopConfig {
    api_host: String,
    server_mode_host: String,
    chunk_threshold: usize,
}

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            service: ServiceConfig::default(),
            desktop: DesktopConfig::default(),
        }
    }
}

impl Default for ServiceConfig {
    fn default() -> Self {
        Self {
            host: "127.0.0.1".to_string(),
            port: 5517,
            engine: "kokoro".to_string(),
            default_voice: "af_bella".to_string(),
            default_rate: 1.0,
            default_format: "mp3".to_string(),
            max_input_length: 50_000,
        }
    }
}

impl Default for DesktopConfig {
    fn default() -> Self {
        Self {
            api_host: "127.0.0.1".to_string(),
            server_mode_host: "0.0.0.0".to_string(),
            chunk_threshold: 800,
        }
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ServiceInfo {
    base_url: String,
    loopback_url: String,
    port: u16,
    chunk_threshold: usize,
    service_running: bool,
    server_mode: bool,
    lan_url: Option<String>,
    last_error: Option<String>,
}

#[tauri::command]
fn get_service_state(
    state: State<'_, ServiceManager>,
    config: State<'_, AppConfigState>,
) -> Result<ServiceInfo, String> {
    let mut runtime = state
        .0
        .lock()
        .map_err(|_| "Service state lock poisoned".to_string())?;
    refresh_service_runtime(&mut runtime)?;
    Ok(service_info(&runtime, &config.0))
}

#[tauri::command]
fn toggle_server_mode(
    app: AppHandle,
    state: State<'_, ServiceManager>,
    config: State<'_, AppConfigState>,
    enable: bool,
) -> Result<ServiceInfo, String> {
    let mut runtime = state
        .0
        .lock()
        .map_err(|_| "Service state lock poisoned".to_string())?;
    if runtime.server_mode == enable {
        return Ok(service_info(&runtime, &config.0));
    }

    let previous_mode = runtime.server_mode;
    runtime.server_mode = enable;
    match restart_service(&app, &config.0, &mut runtime) {
        Ok(info) => Ok(info),
        Err(err) => {
            runtime.server_mode = previous_mode;
            let _ = restart_service(&app, &config.0, &mut runtime);
            Err(err)
        }
    }
}

#[tauri::command]
fn write_audio_file(path: String, data: Vec<u8>) -> Result<String, String> {
    let path = PathBuf::from(path);
    let final_path = if path.extension().is_some() {
        path
    } else {
        path.with_extension("mp3")
    };

    fs::write(&final_path, data).map_err(|err| format!("Failed to write file: {err}"))?;
    Ok(final_path.display().to_string())
}

fn service_info(runtime: &ServiceRuntime, config: &AppConfig) -> ServiceInfo {
    let loopback_url = format!("http://{}:{}", config.desktop.api_host, config.service.port);
    ServiceInfo {
        base_url: loopback_url.clone(),
        loopback_url,
        port: config.service.port,
        chunk_threshold: config.desktop.chunk_threshold,
        service_running: runtime.child.is_some(),
        server_mode: runtime.server_mode,
        lan_url: if runtime.server_mode {
            detect_lan_url(config.service.port)
        } else {
            None
        },
        last_error: runtime.last_error.clone(),
    }
}

fn detect_lan_url(port: u16) -> Option<String> {
    let socket = UdpSocket::bind("0.0.0.0:0").ok()?;
    socket.connect("8.8.8.8:80").ok()?;
    let ip = socket.local_addr().ok()?.ip();
    Some(format!("http://{ip}:{port}"))
}

fn looks_like_project_root(path: &PathBuf) -> bool {
    path.join("pyproject.toml").is_file() && path.join("service").is_dir()
}

fn resolve_project_root(app: &AppHandle) -> PathBuf {
    let base = if cfg!(debug_assertions) {
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..")
    } else {
        app.path()
            .resource_dir()
            .unwrap_or_else(|_| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(".."))
    };

    let bundled_root = base.join("_up_");
    if looks_like_project_root(&base) {
        base
    } else if looks_like_project_root(&bundled_root) {
        bundled_root
    } else {
        base
    }
}

fn resolve_config_path(project_root: &PathBuf) -> PathBuf {
    if let Some(explicit) = env::var_os("LV_CONFIG_FILE") {
        return PathBuf::from(explicit);
    }
    project_root.join("config.yml")
}

fn load_app_config(project_root: &PathBuf) -> Result<AppConfig, String> {
    let config_path = resolve_config_path(project_root);
    if !config_path.exists() {
        return Ok(AppConfig::default());
    }

    let contents = fs::read_to_string(&config_path)
        .map_err(|err| format!("Failed to read {}: {err}", config_path.display()))?;
    serde_yaml::from_str::<AppConfig>(&contents)
        .map_err(|err| format!("Failed to parse {}: {err}", config_path.display()))
}

fn resolve_uv_binary() -> Option<PathBuf> {
    if let Some(path) = env::var_os("PATH") {
        for entry in env::split_paths(&path) {
            let candidate = entry.join("uv");
            if candidate.is_file() {
                return Some(candidate);
            }
        }
    }

    let home = env::var_os("HOME").map(PathBuf::from);
    let candidates = [
        Some(PathBuf::from("/opt/homebrew/bin/uv")),
        Some(PathBuf::from("/usr/local/bin/uv")),
        home.as_ref().map(|path| path.join(".local/bin/uv")),
        home.as_ref().map(|path| path.join(".cargo/bin/uv")),
    ];

    candidates
        .into_iter()
        .flatten()
        .find(|candidate| candidate.is_file())
}

fn bundled_runtime_root(project_root: &Path, is_debug: bool) -> PathBuf {
    if is_debug {
        project_root.join(".venv")
    } else {
        project_root.join(".bundle-venv")
    }
}

fn resolve_venv_python(venv_root: &Path) -> Option<PathBuf> {
    let candidates = if cfg!(windows) {
        vec![venv_root.join("Scripts").join("python.exe")]
    } else {
        vec![
            venv_root.join("bin").join("python"),
            venv_root.join("bin").join("python3"),
        ]
    };

    candidates.into_iter().find(|candidate| candidate.is_file())
}

fn resolve_service_launch_runtime(
    project_root: &Path,
    is_debug: bool,
    uv_binary: Option<PathBuf>,
) -> Result<ServiceLaunchRuntime, String> {
    let runtime_root = bundled_runtime_root(project_root, is_debug);
    let bundled_python = resolve_venv_python(&runtime_root);

    if !is_debug {
        let python_binary = bundled_python.ok_or_else(|| {
            "Packaged Local Voice Desktop is missing a bundled `.bundle-venv`. Rebuild the app with `./build.sh` to prepare the release runtime."
                .to_string()
        })?;

        if !bundled_python_runtime_complete(&runtime_root) {
            return Err(
                "Packaged Local Voice Desktop is missing a complete bundled Python runtime. Rebuild the app so `.bundle-venv` is refreshed."
                    .to_string(),
            );
        }

        return Ok(ServiceLaunchRuntime::BundledPython(python_binary));
    }

    if let Some(python_binary) = bundled_python {
        return Ok(ServiceLaunchRuntime::BundledPython(python_binary));
    }

    let uv_binary = uv_binary.ok_or_else(|| {
        "Could not find a local `.venv` or `uv`. Run `uv sync` before starting the desktop app in development, or install `uv` and ensure it is on PATH."
            .to_string()
    })?;
    Ok(ServiceLaunchRuntime::Uv(uv_binary))
}

fn bundled_python_runtime_complete(venv_root: &Path) -> bool {
    if cfg!(windows) {
        return true;
    }

    let lib_dir = venv_root.join("lib");
    let entries = match fs::read_dir(&lib_dir) {
        Ok(entries) => entries,
        Err(_) => return false,
    };

    entries.flatten().any(|entry| {
        entry
            .file_name()
            .to_str()
            .map(|name| name.starts_with("libpython") && name.ends_with(".dylib"))
            .unwrap_or(false)
    })
}

fn uv_environment_dir() -> PathBuf {
    env::temp_dir().join("local-voice-desktop").join("uv-env")
}

fn uv_cache_dir() -> PathBuf {
    env::temp_dir().join("local-voice-desktop").join("uv-cache")
}

fn runtime_base_dir() -> PathBuf {
    env::temp_dir().join("local-voice-desktop")
}

fn service_log_path() -> PathBuf {
    runtime_base_dir().join("service.log")
}

fn desktop_service_cache_dir(app: &AppHandle) -> PathBuf {
    app.path()
        .app_cache_dir()
        .unwrap_or_else(|_| runtime_base_dir().join("app-cache"))
        .join("service-cache")
}

fn desktop_service_output_dir(app: &AppHandle) -> PathBuf {
    app.path()
        .app_data_dir()
        .unwrap_or_else(|_| runtime_base_dir().join("app-data"))
        .join("service-output")
}

fn configure_release_stdio(command: &mut Command, log_path: &Path) -> Result<(), String> {
    if let Some(parent) = log_path.parent() {
        fs::create_dir_all(parent)
            .map_err(|err| format!("Failed to prepare service log directory: {err}"))?;
    }

    let stdout = OpenOptions::new()
        .create(true)
        .truncate(true)
        .write(true)
        .open(log_path)
        .map_err(|err| format!("Failed to open service log: {err}"))?;
    let stderr = stdout
        .try_clone()
        .map_err(|err| format!("Failed to prepare service log: {err}"))?;
    command
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr));
    Ok(())
}

fn latest_log_line(path: &Path, max_bytes: u64) -> Option<String> {
    let mut file = File::open(path).ok()?;
    let len = file.metadata().ok()?.len();
    let start = len.saturating_sub(max_bytes);
    file.seek(SeekFrom::Start(start)).ok()?;
    let mut buffer = String::new();
    file.read_to_string(&mut buffer).ok()?;
    let line = buffer
        .lines()
        .rev()
        .find(|line| !line.trim().is_empty())?
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ");

    if line.is_empty() {
        None
    } else if line.chars().count() <= 220 {
        Some(line)
    } else {
        let mut truncated = line.chars().take(217).collect::<String>();
        truncated.push_str("...");
        Some(truncated)
    }
}

fn format_service_exit(status: ExitStatus, log_path: Option<&Path>) -> String {
    let base = format!("Local Voice service exited before it became ready ({status}).");
    match log_path.and_then(|path| latest_log_line(path, 8192)) {
        Some(line) => format!("{base} {line}"),
        None => base,
    }
}

fn refresh_service_runtime(runtime: &mut ServiceRuntime) -> Result<(), String> {
    let status = if let Some(child) = runtime.child.as_mut() {
        child
            .try_wait()
            .map_err(|err| format!("Failed to query service status: {err}"))?
    } else {
        None
    };

    if let Some(status) = status {
        runtime.child = None;
        runtime.last_error = Some(format_service_exit(status, runtime.log_path.as_deref()));
    }

    Ok(())
}

fn build_service_command(
    app: &AppHandle,
    config: &AppConfig,
    server_mode: bool,
) -> Result<ServiceLaunch, String> {
    let project_root = resolve_project_root(app);
    let host = if server_mode {
        config.desktop.server_mode_host.clone()
    } else {
        config.desktop.api_host.clone()
    };
    let mut log_path = None;

    let mut command = match resolve_service_launch_runtime(
        &project_root,
        cfg!(debug_assertions),
        resolve_uv_binary(),
    )? {
        ServiceLaunchRuntime::BundledPython(python_binary) => {
            let mut command = Command::new(python_binary);
            command.arg("-m").arg("uvicorn");
            command
        }
        ServiceLaunchRuntime::Uv(uv_binary) => {
            let uv_env = uv_environment_dir();
            let uv_cache = uv_cache_dir();

            fs::create_dir_all(&uv_env)
                .map_err(|err| format!("Failed to prepare uv environment: {err}"))?;
            fs::create_dir_all(&uv_cache)
                .map_err(|err| format!("Failed to prepare uv cache: {err}"))?;

            let mut command = Command::new(uv_binary);
            command
                .env("UV_PROJECT_ENVIRONMENT", uv_env)
                .env("UV_CACHE_DIR", uv_cache)
                .arg("run")
                .arg("uvicorn");
            command
        }
    };
    #[cfg(unix)]
    command.process_group(0);
    command
        .current_dir(project_root)
        .env("LV_HOST", &host)
        .env("LV_PORT", config.service.port.to_string())
        .env("LV_ENGINE", &config.service.engine)
        .env("LV_VOICE", &config.service.default_voice)
        .env("LV_MAX_INPUT", config.service.max_input_length.to_string())
        .env("LV_CACHE_DIR", desktop_service_cache_dir(app))
        .env("LV_OUTPUT_DIR", desktop_service_output_dir(app))
        .env("PYTHONUNBUFFERED", "1")
        .arg("service.app:app")
        .arg("--host")
        .arg(&host)
        .arg("--port")
        .arg(config.service.port.to_string());

    if cfg!(debug_assertions) {
        command.stdout(Stdio::inherit()).stderr(Stdio::inherit());
    } else {
        let path = service_log_path();
        configure_release_stdio(&mut command, &path)?;
        log_path = Some(path);
    }

    Ok(ServiceLaunch { command, log_path })
}

fn stop_service(runtime: &mut ServiceRuntime) -> Result<(), String> {
    if let Some(mut child) = runtime.child.take() {
        #[cfg(unix)]
        {
            let _ = unsafe { killpg(child.id() as i32, SIGKILL) };
        }
        match child.kill() {
            Ok(_) => {}
            Err(err)
                if matches!(
                    err.kind(),
                    std::io::ErrorKind::InvalidInput | std::io::ErrorKind::NotFound
                ) => {}
            Err(err) => return Err(format!("Failed to stop service: {err}")),
        }
        let _ = child.wait();
    }
    runtime.log_path = None;
    Ok(())
}

fn restart_service(
    app: &AppHandle,
    config: &AppConfig,
    runtime: &mut ServiceRuntime,
) -> Result<ServiceInfo, String> {
    stop_service(runtime)?;

    let ServiceLaunch {
        mut command,
        log_path,
    } = build_service_command(app, config, runtime.server_mode)?;
    match command.spawn() {
        Ok(child) => {
            runtime.child = Some(child);
            runtime.log_path = log_path;
            runtime.last_error = None;
            let deadline = Instant::now() + Duration::from_secs(5);
            while Instant::now() < deadline {
                refresh_service_runtime(runtime)?;
                if runtime.child.is_none() {
                    return Err(runtime
                        .last_error
                        .clone()
                        .unwrap_or_else(|| "Failed to start Local Voice service.".to_string()));
                }
                thread::sleep(Duration::from_millis(250));
            }
            Ok(service_info(runtime, config))
        }
        Err(err) => {
            let message = format!("Failed to start Local Voice service: {err}");
            runtime.log_path = None;
            runtime.last_error = Some(message.clone());
            Err(message)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn temp_test_dir(label: &str) -> PathBuf {
        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system time before unix epoch")
            .as_nanos();
        env::temp_dir().join(format!("local-voice-{label}-{unique}"))
    }

    fn failing_exit_status() -> ExitStatus {
        if cfg!(windows) {
            Command::new("cmd")
                .args(["/C", "exit 1"])
                .status()
                .expect("capture failing exit status")
        } else {
            Command::new("sh")
                .args(["-c", "exit 1"])
                .status()
                .expect("capture failing exit status")
        }
    }

    #[test]
    fn project_root_detection_requires_config_and_service_dir() {
        let dir = temp_test_dir("project-root");
        fs::create_dir_all(dir.join("service")).expect("create service dir");
        fs::write(
            dir.join("pyproject.toml"),
            "[project]\nname='local-voice'\n",
        )
        .expect("write pyproject");

        assert!(looks_like_project_root(&dir));

        fs::remove_dir_all(&dir).expect("cleanup");
    }

    #[test]
    fn resolves_python_from_project_venv() {
        let dir = temp_test_dir("venv");
        let venv_root = dir.join(".venv");
        let python_path = if cfg!(windows) {
            venv_root.join("Scripts").join("python.exe")
        } else {
            venv_root.join("bin").join("python")
        };
        fs::create_dir_all(python_path.parent().expect("python parent")).expect("create venv bin");
        fs::write(&python_path, "").expect("write python placeholder");

        assert_eq!(resolve_venv_python(&venv_root), Some(python_path));

        fs::remove_dir_all(&dir).expect("cleanup");
    }

    #[test]
    fn release_runtime_root_uses_bundle_runtime_directory() {
        let dir = temp_test_dir("runtime-root");
        fs::create_dir_all(&dir).expect("create dir");

        assert_eq!(bundled_runtime_root(&dir, true), dir.join(".venv"));
        assert_eq!(bundled_runtime_root(&dir, false), dir.join(".bundle-venv"));

        fs::remove_dir_all(&dir).expect("cleanup");
    }

    #[test]
    fn bundled_runtime_check_requires_libpython() {
        let dir = temp_test_dir("bundled-runtime");
        let venv_root = dir.join(".venv");
        fs::create_dir_all(venv_root.join("lib")).expect("create lib dir");

        assert!(!bundled_python_runtime_complete(&venv_root));

        fs::write(venv_root.join("lib").join("libpython3.11.dylib"), "")
            .expect("write libpython placeholder");

        assert!(bundled_python_runtime_complete(&venv_root));

        fs::remove_dir_all(&dir).expect("cleanup");
    }

    #[test]
    fn release_launch_requires_complete_bundled_runtime() {
        let dir = temp_test_dir("release-launch-runtime");
        let python_path = dir.join(".bundle-venv").join("bin").join("python");
        fs::create_dir_all(python_path.parent().expect("python parent")).expect("create venv bin");
        fs::write(&python_path, "").expect("write python placeholder");

        let error = resolve_service_launch_runtime(&dir, false, None)
            .expect_err("release launch should fail without complete runtime");

        assert!(error.contains("complete bundled Python runtime"));

        fs::create_dir_all(dir.join(".bundle-venv").join("lib")).expect("create lib dir");
        fs::write(
            dir.join(".bundle-venv")
                .join("lib")
                .join("libpython3.11.dylib"),
            "",
        )
        .expect("write libpython placeholder");

        assert_eq!(
            resolve_service_launch_runtime(&dir, false, None),
            Ok(ServiceLaunchRuntime::BundledPython(python_path))
        );

        fs::remove_dir_all(&dir).expect("cleanup");
    }

    #[test]
    fn debug_launch_falls_back_to_uv_when_bundled_runtime_is_missing() {
        let dir = temp_test_dir("debug-launch-runtime");
        fs::create_dir_all(&dir).expect("create dir");
        let uv_binary = dir.join("bin").join("uv");
        fs::create_dir_all(uv_binary.parent().expect("uv parent")).expect("create uv bin");
        fs::write(&uv_binary, "").expect("write uv placeholder");

        assert_eq!(
            resolve_service_launch_runtime(&dir, true, Some(uv_binary.clone())),
            Ok(ServiceLaunchRuntime::Uv(uv_binary))
        );

        fs::remove_dir_all(&dir).expect("cleanup");
    }

    #[test]
    fn service_exit_message_includes_log_excerpt() {
        let dir = temp_test_dir("log");
        fs::create_dir_all(&dir).expect("create log dir");
        let log_path = dir.join("service.log");
        fs::write(
            &log_path,
            "booting\nRuntimeError: missing runtime dependency during startup\n",
        )
        .expect("write log");

        let message = format_service_exit(failing_exit_status(), Some(&log_path));

        assert!(message.contains("missing runtime dependency"));

        fs::remove_dir_all(&dir).expect("cleanup");
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let project_root = resolve_project_root(&app.handle().clone());
            let app_config = load_app_config(&project_root)?;

            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

            app.manage(AppConfigState(app_config));
            app.manage(ServiceManager(Mutex::new(ServiceRuntime::default())));

            {
                let config = app.state::<AppConfigState>();
                let state = app.state::<ServiceManager>();
                let mut runtime = state.0.lock().map_err(|_| "Service state lock poisoned")?;
                if let Err(err) = restart_service(&app.handle().clone(), &config.0, &mut runtime) {
                    runtime.last_error = Some(err);
                }
            }

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_service_state,
            toggle_server_mode,
            write_audio_file
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|app_handle, event| match event {
        tauri::RunEvent::WindowEvent {
            event: tauri::WindowEvent::CloseRequested { .. },
            ..
        } => {
            let state = app_handle.state::<ServiceManager>();
            if let Ok(mut runtime) = state.0.lock() {
                let _ = stop_service(&mut runtime);
            }
            app_handle.exit(0);
        }
        tauri::RunEvent::Exit => {
            let state = app_handle.state::<ServiceManager>();
            let mut runtime = match state.0.lock() {
                Ok(guard) => guard,
                Err(_) => return,
            };
            let _ = stop_service(&mut runtime);
        }
        _ => {}
    });
}
