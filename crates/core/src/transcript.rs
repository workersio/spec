use anyhow::{Context, Result};

/// Locate the session JSONL file given a session ID and workspace path.
///
/// Claude Code stores sessions at: ~/.claude/projects/{normalized_cwd}/{session_id}.jsonl
/// where normalized_cwd replaces '/' with '-'.
///
/// If WORKSPACE_PATH resolves to a valid session, use it directly.
/// Otherwise, search all project directories for the session file.
pub fn find_session_file(session_id: &str, workspace_path: &str) -> Result<String> {
    let home = std::env::var("HOME").context("HOME not set")?;
    let projects_dir = format!("{}/.claude/projects", home);
    let filename = format!("{}.jsonl", session_id);

    // Try WORKSPACE_PATH first (fast path for production)
    if let Ok(absolute) = std::fs::canonicalize(workspace_path) {
        let normalized = absolute.to_string_lossy().replace('/', "-");
        let session_path = format!("{}/{}/{}", projects_dir, normalized, filename);
        if std::path::Path::new(&session_path).exists() {
            return Ok(session_path);
        }
    }

    // Fallback: search all project directories
    if let Ok(entries) = std::fs::read_dir(&projects_dir) {
        for entry in entries.flatten() {
            if entry.path().is_dir() {
                let candidate = entry.path().join(&filename);
                if candidate.exists() {
                    return Ok(candidate.to_string_lossy().to_string());
                }
            }
        }
    }

    anyhow::bail!(
        "Session file {}.jsonl not found in any project directory under {}",
        session_id,
        projects_dir
    )
}
