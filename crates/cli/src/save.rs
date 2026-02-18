use anyhow::{Context, Result};
use std::path::Path;
use workers_spec_core::parse_spec;

use crate::generate::generate_spec;

pub async fn run(session_id: &str, workspace: Option<&str>) -> Result<()> {
    let spec_content = generate_spec(session_id, workspace).await?;

    let parsed = parse_spec(&spec_content);

    let filename = if parsed.title.is_empty() {
        format!("{session_id}.md")
    } else {
        format!("{}.md", slugify(&parsed.title))
    };

    let spec_dir = Path::new(".spec");
    tokio::fs::create_dir_all(spec_dir)
        .await
        .context("Failed to create .spec directory")?;

    let dest = spec_dir.join(&filename);
    tokio::fs::write(&dest, &spec_content)
        .await
        .context("Failed to write spec file")?;

    eprintln!("Saved to {}", dest.display());

    Ok(())
}

fn slugify(title: &str) -> String {
    let mut result = String::with_capacity(title.len());
    let mut prev_dash = true; // skip leading dashes
    for c in title.chars() {
        if c.is_alphanumeric() {
            result.push(c.to_ascii_lowercase());
            prev_dash = false;
        } else if !prev_dash {
            result.push('-');
            prev_dash = true;
        }
    }
    if result.ends_with('-') {
        result.pop();
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_slugify() {
        assert_eq!(slugify("Hello World"), "hello-world");
        assert_eq!(slugify("Navigate to Website & Capture"), "navigate-to-website-capture");
        assert_eq!(slugify("  Lots   of   spaces  "), "lots-of-spaces");
        assert_eq!(slugify("Already-Slugged"), "already-slugged");
        assert_eq!(slugify("Special!@#Chars"), "special-chars");
    }
}
