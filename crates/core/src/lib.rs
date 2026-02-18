pub mod spec_parser;
pub mod transcript;

pub use spec_parser::{parse_spec, ParsedSpec};
pub use transcript::find_session_file;

/// The prompt template used to generate specs from Claude Code sessions.
/// Contains a `{transcript}` placeholder that gets replaced with the session JSONL content.
pub const PROMPT_TEMPLATE: &str = include_str!("../prompt.md");

#[derive(Debug, thiserror::Error)]
pub enum SpecError {
    #[error("Home directory not found")]
    HomeNotFound,
    #[error("Session file {session_id}.jsonl not found in any project directory under {projects_dir}")]
    SessionNotFound {
        session_id: String,
        projects_dir: String,
    },
    #[error("Failed to read directory: {0}")]
    Io(#[from] std::io::Error),
}
