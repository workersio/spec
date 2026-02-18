use anyhow::{Context, Result};
use cliclack::{intro, input, outro, select, spinner};
use std::path::PathBuf;

use crate::config::Config;

const SHARE_COMMAND: &str = include_str!("../../../commands/share.md");
const RUN_COMMAND: &str = include_str!("../../../commands/run.md");

pub async fn run() -> Result<()> {
    intro("workers-spec")?;

    // Step 1: Server URL
    let server_url: String = input("Server URL:")
        .default_input("https://spec.workers.io")
        .interact()?;

    // Step 2: Command installation scope
    let scope: &str = select("Where to install slash commands?")
        .item("workspace", "This workspace", ".claude/commands/")
        .item("global", "Global", "~/.claude/commands/")
        .interact()?;

    // Step 3: Save config
    let config = Config {
        api_url: server_url.clone(),
    };
    config.save()?;

    // Step 4: Install commands
    let dest = match scope {
        "workspace" => PathBuf::from(".claude/commands"),
        _ => {
            let home = dirs::home_dir().context("Could not determine home directory")?;
            home.join(".claude/commands")
        }
    };
    tokio::fs::create_dir_all(&dest).await.context("Failed to create commands directory")?;
    tokio::fs::write(dest.join("share.md"), SHARE_COMMAND).await.context("Failed to write share.md")?;
    tokio::fs::write(dest.join("run.md"), RUN_COMMAND).await.context("Failed to write run.md")?;

    // Step 5: Check connectivity
    let sp = spinner();
    sp.start("Checking server connectivity...");
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(5))
        .build()?;
    match client
        .get(format!("{server_url}/health"))
        .send()
        .await
    {
        Ok(resp) if resp.status().is_success() => sp.stop("Connected"),
        _ => sp.stop("Server unreachable (you can fix this later with `workers-spec config`)"),
    }

    outro("Setup complete! Use /share in Claude Code to share a session.")?;
    Ok(())
}
