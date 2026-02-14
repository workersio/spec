use tracing::debug;

/// Parsed specification with frontmatter metadata and markdown body.
pub struct ParsedSpec {
    pub title: String,
    pub description: String,
    pub tags: Vec<String>,
    pub body: String, // markdown body (without frontmatter) — becomes the task prompt
    pub raw: String,  // full content (frontmatter + body) — stored as-is
}

/// Parse spec.md content: extract YAML frontmatter + markdown body.
///
/// Expected format:
/// ```text
/// ---
/// title: "Short name"
/// description: "One-liner"
/// tags: ["tag1", "tag2"]
/// ---
///
/// ## Objective
/// ...
/// ```
pub fn parse_spec(content: &str) -> ParsedSpec {
    let raw = content.to_string();

    // Try to split on frontmatter delimiters
    let (title, description, tags, body) = match parse_frontmatter(content) {
        Some((fm_title, fm_desc, fm_tags, fm_body)) => (fm_title, fm_desc, fm_tags, fm_body),
        None => {
            debug!("No frontmatter found in spec.md, using full content as body");
            (String::new(), String::new(), Vec::new(), content.to_string())
        }
    };

    debug!(
        "Parsed spec: title={:?}, description=({} chars), tags={:?}, body=({} bytes)",
        title,
        description.len(),
        tags,
        body.len()
    );

    ParsedSpec {
        title,
        description,
        tags,
        body,
        raw,
    }
}

/// Parse YAML frontmatter from content. Returns None if no valid frontmatter found.
fn parse_frontmatter(content: &str) -> Option<(String, String, Vec<String>, String)> {
    let trimmed = content.trim_start();

    // Must start with "---"
    if !trimmed.starts_with("---") {
        return None;
    }

    // Find the closing "---" delimiter
    let after_first = trimmed[3..].trim_start_matches(['\r', '\n']);
    let end_idx = after_first.find("\n---")?;

    let frontmatter = &after_first[..end_idx];
    let body = after_first[end_idx + 4..].trim_start_matches(['\r', '\n']);

    let mut title = String::new();
    let mut description = String::new();
    let mut tags = Vec::new();

    for line in frontmatter.lines() {
        let line = line.trim();
        if let Some(val) = strip_yaml_field(line, "title") {
            title = val;
        } else if let Some(val) = strip_yaml_field(line, "description") {
            description = val;
        } else if let Some(rest) = line.strip_prefix("tags:") {
            tags = parse_yaml_array(rest.trim());
        }
    }

    Some((title, description, tags, body.to_string()))
}

/// Extract value from a YAML field line like `title: "Some Title"` or `title: Some Title`.
fn strip_yaml_field(line: &str, field: &str) -> Option<String> {
    let prefix = format!("{field}:");
    if !line.starts_with(&prefix) {
        return None;
    }
    let val = line[prefix.len()..].trim();
    // Strip surrounding quotes if present
    let val = val
        .strip_prefix('"')
        .and_then(|v| v.strip_suffix('"'))
        .unwrap_or(val);
    Some(val.to_string())
}

/// Parse a YAML inline array like `["tag1", "tag2", "tag3"]`.
fn parse_yaml_array(s: &str) -> Vec<String> {
    let s = s.trim();
    let inner = s
        .strip_prefix('[')
        .and_then(|v| v.strip_suffix(']'))
        .unwrap_or(s);

    inner
        .split(',')
        .map(|t| {
            t.trim()
                .trim_matches('"')
                .trim_matches('\'')
                .to_string()
        })
        .filter(|t| !t.is_empty())
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_full_spec() {
        let input = r#"---
title: "Navigate to Website and Capture Screenshot"
description: "Automate browser navigation to a specified URL and capture a screenshot"
tags: ["browser-automation", "screenshot", "web-navigation"]
---

## Objective

Navigate to a website and capture a screenshot.

## Requirements

### Requirement: Browser Delegation

The agent MUST delegate browser tasks to the kernel-browser subagent."#;

        let result = parse_spec(input);
        assert_eq!(result.title, "Navigate to Website and Capture Screenshot");
        assert_eq!(
            result.description,
            "Automate browser navigation to a specified URL and capture a screenshot"
        );
        assert_eq!(
            result.tags,
            vec!["browser-automation", "screenshot", "web-navigation"]
        );
        assert!(result.body.starts_with("## Objective"));
        assert!(result.body.contains("### Requirement: Browser Delegation"));
        assert!(!result.body.contains("---"));
        assert!(result.raw.starts_with("---"));
    }

    #[test]
    fn test_parse_no_frontmatter() {
        let input = "## Objective\n\nJust a plain spec.";
        let result = parse_spec(input);
        assert_eq!(result.title, "");
        assert_eq!(result.description, "");
        assert!(result.tags.is_empty());
        assert_eq!(result.body, input);
    }

    #[test]
    fn test_parse_unquoted_values() {
        let input = "---\ntitle: My Spec\ndescription: A simple description\ntags: [a, b]\n---\n\nBody here.";
        let result = parse_spec(input);
        assert_eq!(result.title, "My Spec");
        assert_eq!(result.description, "A simple description");
        assert_eq!(result.tags, vec!["a", "b"]);
        assert_eq!(result.body, "Body here.");
    }

    #[test]
    fn test_parse_empty_tags() {
        let input = "---\ntitle: Test\ndescription: Desc\ntags: []\n---\n\nBody.";
        let result = parse_spec(input);
        assert!(result.tags.is_empty());
    }
}
