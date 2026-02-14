use anyhow::{Context, Result};
use std::process::Stdio;
use tracing::{error, info};
use workers_spec_core::{find_session_file, PROMPT_TEMPLATE};

use crate::config::Config;

pub async fn run(session_id: &str, workspace: Option<&str>) -> Result<()> {
    let config = Config::load()?;
    let workspace_path = workspace.unwrap_or(".");

    let session_file = find_session_file(session_id, workspace_path)?;
    info!("Found session file: {}", session_file);

    let transcript = tokio::fs::read_to_string(&session_file)
        .await
        .context("Failed to read session file")?;

    let prompt = PROMPT_TEMPLATE.replace("{transcript}", &transcript);

    eprintln!("Generating spec from session {}...", session_id);

    let output = tokio::process::Command::new("claude")
        .arg("-p")
        .arg(&prompt)
        .arg("--dangerously-skip-permissions")
        .env_remove("CLAUDECODE")
        .stdin(Stdio::null())
        .output()
        .await
        .context("Failed to spawn claude. Is Claude CLI installed?")?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        error!("Claude exited with {}: {}", output.status, stderr);
        anyhow::bail!("Spec generation failed");
    }

    let spec_content = String::from_utf8_lossy(&output.stdout);
    let spec_content = spec_content.trim();
    if spec_content.is_empty() {
        anyhow::bail!("Claude produced no output");
    }

    info!("Generated spec: {} bytes", spec_content.len());

    let client = reqwest::Client::new();
    let resp = client
        .post(format!("{}/api/specs", config.api_url))
        .json(&serde_json::json!({ "content": spec_content, "version": env!("CARGO_PKG_VERSION") }))
        .send()
        .await
        .context("Failed to upload spec")?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        anyhow::bail!("API returned {}: {}", status, body);
    }

    let result: serde_json::Value = resp.json().await.context("Failed to parse API response")?;
    let url = result["url"].as_str().context("API response missing 'url'")?;

    println!("{}", url);

    Ok(())
}
