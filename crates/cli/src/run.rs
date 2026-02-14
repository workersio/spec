use anyhow::{Context, Result};
use serde::Deserialize;

use crate::config::Config;

#[derive(Deserialize)]
struct SpecResponse {
    content: String,
    title: String,
    summary: String,
    step_count: i64,
}

/// Parse input into (api_base_url, spec_id).
/// If input is a full URL like `http://host:port/s/abc123`, extract the host and ID.
/// Otherwise treat it as a raw ID and use the configured api_url.
fn parse_spec_input(input: &str, config_api_url: &str) -> (String, String) {
    if let Some(pos) = input.rfind("/s/") {
        let id = input[pos + 3..].to_string();
        let base = input[..pos].to_string();
        if !base.is_empty() {
            return (base, id);
        }
    }
    if input.contains('/') {
        if let Some(last) = input.rsplit('/').next() {
            if !last.is_empty() {
                return (config_api_url.to_string(), last.to_string());
            }
        }
    }
    (config_api_url.to_string(), input.to_string())
}

pub async fn run(url_or_id: &str, full: bool) -> Result<()> {
    let config = Config::load()?;
    let (api_base, id) = parse_spec_input(url_or_id, &config.api_url);

    let client = reqwest::Client::new();
    let resp = client
        .get(format!("{}/api/specs/{}", api_base, id))
        .send()
        .await
        .context("Failed to fetch spec from API")?;

    if resp.status() == reqwest::StatusCode::NOT_FOUND {
        anyhow::bail!("Spec '{}' not found", id);
    }

    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        anyhow::bail!("API returned {}: {}", status, body);
    }

    let spec: SpecResponse = resp.json().await.context("Failed to parse spec response")?;

    if full {
        print!("{}", spec.content);
    } else {
        // Preview: title, step count, step headings
        println!("Title: {}", spec.title);
        if !spec.summary.is_empty() {
            println!("Summary: {}", spec.summary);
        }
        println!("Steps: {}", spec.step_count);

        // Section headings
        let headings: Vec<&str> = spec
            .content
            .lines()
            .filter(|l| l.starts_with("## "))
            .map(|l| l.trim_start_matches('#').trim())
            .collect();

        if !headings.is_empty() {
            println!("\nSections:");
            for h in &headings {
                println!("  - {}", h);
            }
        }
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    const DEFAULT: &str = "http://localhost:3005";

    #[test]
    fn test_parse_full_url_extracts_host_and_id() {
        let (base, id) = parse_spec_input("https://example.com/s/abc123", DEFAULT);
        assert_eq!(base, "https://example.com");
        assert_eq!(id, "abc123");
    }

    #[test]
    fn test_parse_url_with_port() {
        let (base, id) = parse_spec_input("http://137.184.115.125:3005/s/xyz789", DEFAULT);
        assert_eq!(base, "http://137.184.115.125:3005");
        assert_eq!(id, "xyz789");
    }

    #[test]
    fn test_parse_raw_id_uses_config() {
        let (base, id) = parse_spec_input("abc123", DEFAULT);
        assert_eq!(base, DEFAULT);
        assert_eq!(id, "abc123");
    }

    #[test]
    fn test_parse_localhost_url() {
        let (base, id) = parse_spec_input("http://localhost:3000/s/test_id", DEFAULT);
        assert_eq!(base, "http://localhost:3000");
        assert_eq!(id, "test_id");
    }
}
