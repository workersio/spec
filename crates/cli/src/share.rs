use anyhow::{Context, Result};

use crate::config::Config;
use crate::generate::generate_spec;

pub async fn run(session_id: &str, workspace: Option<&str>) -> Result<()> {
    let config = Config::load()?;

    let spec_content = generate_spec(session_id, workspace).await?;

    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(30))
        .build()?;
    let resp = client
        .post(format!("{}/api/specs", config.api_url))
        .json(&serde_json::json!({ "content": spec_content, "version": env!("CARGO_PKG_VERSION") }))
        .send()
        .await
        .context("Failed to upload spec")?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        anyhow::bail!("API returned {status}: {body}");
    }

    let result: serde_json::Value = resp.json().await.context("Failed to parse API response")?;
    let url = result["url"].as_str().context("API response missing 'url'")?;

    println!("{url}");

    Ok(())
}
