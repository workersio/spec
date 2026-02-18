use crate::SpecError;

/// Locate the session JSONL file given a session ID and workspace path.
///
/// Claude Code stores sessions at: ~/.claude/projects/{normalized_cwd}/{session_id}.jsonl
/// where normalized_cwd replaces '/' with '-'.
///
/// If WORKSPACE_PATH resolves to a valid session, use it directly.
/// Otherwise, search all project directories for the session file.
pub fn find_session_file(session_id: &str, workspace_path: &str) -> Result<String, SpecError> {
    let home = dirs::home_dir().ok_or(SpecError::HomeNotFound)?;
    let projects_dir = home.join(".claude/projects");
    let projects_dir_str = projects_dir.to_string_lossy().to_string();
    let filename = format!("{session_id}.jsonl");

    // Try WORKSPACE_PATH first (fast path for production)
    if let Ok(absolute) = std::fs::canonicalize(workspace_path) {
        let normalized = absolute.to_string_lossy().replace('/', "-");
        let session_path = projects_dir.join(&normalized).join(&filename);
        if session_path.exists() {
            return Ok(session_path.to_string_lossy().to_string());
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

    Err(SpecError::SessionNotFound {
        session_id: session_id.to_string(),
        projects_dir: projects_dir_str,
    })
}
