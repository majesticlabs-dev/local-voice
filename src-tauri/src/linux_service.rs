use super::ServiceRuntime;
use std::fs;
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::os::unix::fs::PermissionsExt;
use std::process::Command;
use std::thread;
use std::time::{Duration, Instant};
use tauri::{AppHandle, Manager};

const UNIT: &str = "local-voice.service";

fn unit_active() -> Result<bool, String> {
    let result = Command::new("systemctl")
        .args(["--user", "is-active", "--quiet", UNIT])
        .status()
        .map_err(|e| format!("Cannot query the user service: {e}"))?;
    Ok(result.success())
}

fn probe(port: u16) -> bool {
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_millis(250)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(500)));
    if stream
        .write_all(b"GET /health HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
        .is_err()
    {
        return false;
    }
    let mut buffer = [0; 64];
    stream.read(&mut buffer).is_ok_and(|n| {
        buffer[..n].starts_with(b"HTTP/1.1 200") || buffer[..n].starts_with(b"HTTP/1.0 200")
    })
}

fn port_occupied(port: u16) -> bool {
    TcpStream::connect_timeout(
        &SocketAddr::from(([127, 0, 0, 1], port)),
        Duration::from_millis(250),
    )
    .is_ok()
}

pub(super) fn refresh(runtime: &mut ServiceRuntime, port: u16) -> Result<(), String> {
    runtime.last_error = if unit_active()? {
        if probe(port) {
            None
        } else {
            Some(format!(
                "{UNIT} is active but /health is not ready. Check journalctl --user -u {UNIT}."
            ))
        }
    } else if port_occupied(port) {
        Some(format!("Port {port} is occupied by a standalone or other service. Stop it yourself before starting {UNIT}; Local Voice will not kill it."))
    } else {
        Some(format!(
            "{UNIT} is stopped. Check journalctl --user -u {UNIT}."
        ))
    };
    Ok(())
}

pub(super) fn start(port: u16, runtime: &mut ServiceRuntime) -> Result<(), String> {
    if !unit_active()? {
        if port_occupied(port) {
            return Err(format!("Port {port} is occupied by a standalone or other service. Stop it yourself; Local Voice will not kill it."));
        }
        let output = Command::new("systemctl")
            .args(["--user", "start", UNIT])
            .output()
            .map_err(|e| format!("Cannot start {UNIT}: {e}"))?;
        if !output.status.success() {
            return Err(format!(
                "Cannot start {UNIT}: {}. Check journalctl --user -u {UNIT}.",
                String::from_utf8_lossy(&output.stderr).trim()
            ));
        }
    }
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        refresh(runtime, port)?;
        if runtime.last_error.is_none() {
            return Ok(());
        }
        if Instant::now() >= deadline || !unit_active()? {
            return Err(runtime.last_error.clone().unwrap_or_default());
        }
        thread::sleep(Duration::from_millis(200));
    }
}

fn management_route(action: &str, job_id: Option<&str>) -> Result<(&'static str, String), String> {
    let id = match job_id {
        Some(id)
            if !id.is_empty() && id.len() <= 64 && id.bytes().all(|b| b.is_ascii_hexdigit()) =>
        {
            id
        }
        None => "",
        _ => return Err("Invalid job ID".into()),
    };
    match (action, id.is_empty()) {
        ("catalog", true) => Ok(("GET", "/models".into())),
        ("download", true) => Ok(("POST", "/models/downloads".into())),
        ("remove", true) => Ok(("POST", "/models/removals".into())),
        ("job", false) => Ok(("GET", format!("/models/downloads/{id}"))),
        ("cancel", false) => Ok(("POST", format!("/models/downloads/{id}/cancel"))),
        _ => Err("Invalid model management action".into()),
    }
}

pub(super) fn manage_models(
    app: &AppHandle,
    action: &str,
    job_id: Option<&str>,
    languages: Option<Vec<String>>,
) -> Result<serde_json::Value, String> {
    let (method, route) = management_route(action, job_id)?;
    let path = app
        .path()
        .app_data_dir()
        .map_err(|e| e.to_string())?
        .join("management-token");
    let metadata = fs::symlink_metadata(&path)
        .map_err(|e| format!("Shared service token unavailable: {e}"))?;
    if !metadata.file_type().is_file() || metadata.permissions().mode() & 0o077 != 0 {
        return Err("Shared service token is not a private regular file".into());
    }
    let token = fs::read_to_string(&path).map_err(|e| e.to_string())?;
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(15))
        .build()
        .map_err(|e| e.to_string())?;
    let url = format!("http://127.0.0.1:5517{route}");
    let request = if method == "GET" {
        client.get(url)
    } else {
        client.post(url)
    };
    let request = request.header("X-Local-Voice-Management", token.trim());
    let request = if matches!(action, "download" | "remove") {
        let ids = languages.ok_or("Languages required")?;
        if ids.is_empty()
            || ids
                .iter()
                .any(|id| !matches!(id.as_str(), "en" | "es" | "ru"))
        {
            return Err("Invalid language selection".into());
        }
        request.json(&serde_json::json!({"languages": ids}))
    } else {
        request
    };
    let response = request
        .send()
        .map_err(|e| format!("Shared service unavailable: {e}"))?;
    let status = response.status();
    let body: serde_json::Value = response
        .json()
        .map_err(|e| format!("Invalid service response: {e}"))?;
    if !status.is_success() {
        return Err(format!("Model management failed ({status}): {body}"));
    }
    Ok(body)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpListener;

    #[test]
    fn management_routes_are_bounded() {
        assert_eq!(management_route("catalog", None).unwrap().1, "/models");
        assert!(management_route("job", Some("../health")).is_err());
        assert!(management_route("download", Some("abc")).is_err());
    }

    #[test]
    fn port_probe_does_not_accept_an_unrelated_listener() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        assert!(port_occupied(port));
        assert!(!probe(port));
    }
}
