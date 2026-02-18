use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;

#[derive(Serialize, Deserialize)]
pub struct Config {
    pub api_url: String,
}

impl Config {
    pub const DEFAULT_URL: &str = "https://spec.workers.io";

    fn path() -> Result<PathBuf> {
        let home = std::env::var("HOME").context("HOME not set")?;
        Ok(PathBuf::from(home).join(".config/workers-spec/config.toml"))
    }

    pub fn load() -> Result<Self> {
        let path = Self::path()?;
        if path.exists() {
            let content = fs::read_to_string(&path)
                .context("Failed to read config file")?;
            toml::from_str(&content).context("Failed to parse config file")
        } else if let Ok(api_url) = std::env::var("WORKERS_SPEC_API_URL") {
            Ok(Config { api_url })
        } else {
            Ok(Config::default())
        }
    }

    pub fn save(&self) -> Result<()> {
        let path = Self::path()?;
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)
                .context("Failed to create config directory")?;
        }
        let content = toml::to_string_pretty(self).context("Failed to serialize config")?;
        fs::write(&path, content).context("Failed to write config file")?;
        Ok(())
    }
}

impl Default for Config {
    fn default() -> Self {
        Config {
            api_url: Self::DEFAULT_URL.to_string(),
        }
    }
}
