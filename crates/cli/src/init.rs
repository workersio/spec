use anyhow::Result;

use crate::config::Config;

pub fn run(server_url: Option<&str>, reset: bool) -> Result<()> {
    if reset {
        let config = Config::default();
        config.save()?;
        println!("Config reset to default");
        println!("  Server URL: {}", config.api_url);
        return Ok(());
    }

    if let Some(url) = server_url {
        let config = Config {
            api_url: url.to_string(),
        };
        config.save()?;
        println!("Server URL set to: {url}");
    } else {
        let config = Config::load()?;
        let is_default = config.api_url == Config::DEFAULT_URL;
        println!("Server URL: {}", config.api_url);
        if is_default {
            println!("  (default — local server)");
        } else {
            println!("  (custom — remote server)");
        }
        println!("\nUsage:");
        println!("  workers-spec config --server-url <url>   Set remote server");
        println!("  workers-spec config --reset              Reset to local");
    }

    Ok(())
}
