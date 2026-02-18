use anyhow::{Context, Result};
use std::process::Stdio;
use tracing::error;
use workers_spec_core::{find_session_file, PROMPT_TEMPLATE};

/// Generate a spec from a Claude Code session transcript.
///
/// Returns the generated spec content as a string.
pub async fn generate_spec(session_id: &str, workspace: Option<&str>) -> Result<String> {
    let workspace_path = workspace.unwrap_or(".");

    let session_file = find_session_file(session_id, workspace_path)?;

    let transcript = tokio::fs::read_to_string(&session_file)
        .await
        .context("Failed to read session file")?;

    let prompt = PROMPT_TEMPLATE.replace("{transcript}", &transcript);

    eprintln!("Generating spec from session {session_id}...");

    let output = tokio::time::timeout(
        std::time::Duration::from_secs(300),
        tokio::process::Command::new("claude")
            .arg("-p")
            .arg(&prompt)
            .arg("--dangerously-skip-permissions")
            .env_remove("CLAUDECODE")
            .stdin(Stdio::null())
            .output(),
    )
    .await
    .context("Spec generation timed out (5 min limit)")?
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

    Ok(spec_content.to_string())
}
