use anyhow::{Context, Result};
use std::fs;
use std::path::PathBuf;

fn config_dir() -> Result<PathBuf> {
    let home = std::env::var("HOME").context("HOME not set")?;
    Ok(PathBuf::from(home).join(".config/workers-spec"))
}

fn data_dir() -> Result<PathBuf> {
    let home = std::env::var("HOME").context("HOME not set")?;
    Ok(PathBuf::from(home).join(".local/share/workers-spec"))
}

fn pid_path() -> Result<PathBuf> {
    Ok(config_dir()?.join("server.pid"))
}

fn log_path() -> Result<PathBuf> {
    Ok(config_dir()?.join("server.log"))
}

pub fn database_path() -> Result<String> {
    let dir = data_dir()?;
    fs::create_dir_all(&dir).context("Failed to create data directory")?;
    Ok(dir.join("workers-spec.db").to_string_lossy().to_string())
}

/// PID file format: "pid:port"
fn read_pid_file() -> Result<Option<(u32, u16)>> {
    let path = pid_path()?;
    if !path.exists() {
        return Ok(None);
    }
    let content = fs::read_to_string(&path).context("Failed to read PID file")?;
    let content = content.trim();
    let parts: Vec<&str> = content.split(':').collect();
    let pid: u32 = parts[0].parse().context("Invalid PID in file")?;
    let port: u16 = if parts.len() > 1 {
        parts[1].parse().unwrap_or(3005)
    } else {
        3005
    };
    Ok(Some((pid, port)))
}

fn write_pid_file(pid: u32, port: u16) -> Result<()> {
    fs::write(pid_path()?, format!("{}:{}", pid, port)).context("Failed to write PID file")
}

fn is_process_alive(pid: u32) -> bool {
    unsafe { libc::kill(pid as i32, 0) == 0 }
}

pub fn start(port: u16) -> Result<()> {
    let config = crate::config::Config::load()?;
    if config.api_url != crate::config::Config::DEFAULT_URL {
        println!("Using remote server: {}", config.api_url);
        println!("No local server needed.");
        println!("\nTo start a local server instead, run:");
        println!("  workers-spec config --reset");
        println!("  workers-spec start");
        return Ok(());
    }

    if let Some((pid, existing_port)) = read_pid_file()? {
        if is_process_alive(pid) {
            println!("Server already running on port {} (PID {})", existing_port, pid);
            return Ok(());
        }
        let _ = fs::remove_file(pid_path()?);
    }

    let config_dir = config_dir()?;
    fs::create_dir_all(&config_dir).context("Failed to create config directory")?;

    let db_path = database_path()?;
    let log = fs::File::create(log_path()?).context("Failed to create log file")?;
    let log_err = log.try_clone().context("Failed to clone log file handle")?;

    let exe = std::env::current_exe().context("Failed to get current executable path")?;

    let base_url = format!("http://localhost:{}", port);

    let child = std::process::Command::new(exe)
        .arg("serve")
        .arg("--port")
        .arg(port.to_string())
        .arg("--database-path")
        .arg(&db_path)
        .env("BASE_URL", &base_url)
        .stdout(log)
        .stderr(log_err)
        .stdin(std::process::Stdio::null())
        .spawn()
        .context("Failed to start server process")?;

    let pid = child.id();
    write_pid_file(pid, port)?;

    for _ in 0..10 {
        std::thread::sleep(std::time::Duration::from_millis(200));

        if !is_process_alive(pid) {
            let _ = fs::remove_file(pid_path()?);
            let log_content = fs::read_to_string(log_path()?)
                .unwrap_or_default();
            if log_content.contains("Address already in use") {
                anyhow::bail!(
                    "Port {} is already in use. Try a different port:\n  workers-spec start --port {}",
                    port,
                    port + 1
                );
            }
            anyhow::bail!(
                "Server failed to start.\nLog: {}",
                log_content.trim()
            );
        }

        if let Ok(log_content) = fs::read_to_string(log_path()?) {
            if log_content.contains("Server listening on") {
                println!("Server started on port {} (PID {})", port, pid);
                println!("URL: {}", base_url);
                println!("Database: {}", db_path);
                return Ok(());
            }
        }
    }

    let _ = fs::remove_file(pid_path()?);
    if is_process_alive(pid) {
        unsafe { libc::kill(pid as i32, libc::SIGTERM); }
    }
    let log_content = fs::read_to_string(log_path()?).unwrap_or_default();
    if log_content.contains("Address already in use") {
        anyhow::bail!(
            "Port {} is already in use. Try a different port:\n  workers-spec start --port {}",
            port,
            port + 1
        );
    }
    anyhow::bail!("Server failed to start.\nLog: {}", log_content.trim())
}

pub fn stop() -> Result<()> {
    let config = crate::config::Config::load()?;
    if config.api_url != crate::config::Config::DEFAULT_URL {
        println!("Using remote server: {}", config.api_url);
        println!("Nothing to stop locally.");
        return Ok(());
    }

    match read_pid_file()? {
        Some((pid, _port)) => {
            if is_process_alive(pid) {
                unsafe {
                    libc::kill(pid as i32, libc::SIGTERM);
                }
                for _ in 0..20 {
                    std::thread::sleep(std::time::Duration::from_millis(100));
                    if !is_process_alive(pid) {
                        break;
                    }
                }
            }
            let _ = fs::remove_file(pid_path()?);
            println!("Server stopped");
            Ok(())
        }
        None => {
            println!("Server is not running");
            Ok(())
        }
    }
}

pub async fn status() -> Result<()> {
    let config = crate::config::Config::load()?;
    let is_default = config.api_url == crate::config::Config::DEFAULT_URL;

    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(3))
        .build()?;

    if is_default {
        match read_pid_file()? {
            Some((pid, port)) => {
                if is_process_alive(pid) {
                    println!("Local server running on port {} (PID {})", port, pid);

                    match client
                        .get(format!("http://localhost:{}/health", port))
                        .send()
                        .await
                    {
                        Ok(resp) if resp.status().is_success() => {
                            println!("Health: OK");
                        }
                        _ => {
                            println!("Health: unreachable (server may still be starting)");
                        }
                    }
                } else {
                    println!("Server is not running (stale PID file)");
                    let _ = fs::remove_file(pid_path()?);
                }
            }
            None => {
                println!("Server is not running");
                println!("  Run `workers-spec start` to start the local server");
            }
        }
        println!("\nServer URL: {} (local)", config.api_url);
        println!("  Use `workers-spec config --server-url <url>` to set remote");
    } else {
        println!("Server URL: {} (remote)", config.api_url);

        match client
            .get(format!("{}/health", config.api_url))
            .send()
            .await
        {
            Ok(resp) if resp.status().is_success() => {
                println!("Health: OK");
            }
            Ok(resp) => {
                println!("Health: server returned {}", resp.status());
            }
            Err(_) => {
                println!("Health: unreachable");
            }
        }
        println!("  Use `workers-spec config --reset` to switch to local");
    }

    Ok(())
}
