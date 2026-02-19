use serde_json::{Map, Value};
use std::fs;
use std::path::PathBuf;

use crate::registry::Plugin;

const REPO: &str = "github.com/workersio/spec";

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Scope {
    Project,
    User,
}

pub fn settings_path(scope: &Scope) -> PathBuf {
    match scope {
        Scope::Project => {
            let cwd = std::env::current_dir().expect("Failed to get current directory");
            cwd.join(".claude").join("settings.json")
        }
        Scope::User => {
            let home = dirs_path();
            home.join(".claude").join("settings.json")
        }
    }
}

fn dirs_path() -> PathBuf {
    std::env::var("HOME")
        .map(PathBuf::from)
        .expect("Failed to get HOME directory")
}

pub fn install(plugins: &[Plugin], scope: &Scope) -> std::io::Result<()> {
    let path = settings_path(scope);

    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }

    let mut settings: Map<String, Value> = if path.exists() {
        let content = fs::read_to_string(&path)?;
        serde_json::from_str(&content).unwrap_or_default()
    } else {
        Map::new()
    };

    let mut existing_plugins: Vec<Value> = settings
        .get("plugins")
        .and_then(|v| v.as_array().cloned())
        .unwrap_or_default();

    for plugin in plugins {
        let entry = format!("{}{}", REPO, plugin.source.trim_start_matches('.'));
        if !existing_plugins.iter().any(|v| v.as_str() == Some(&entry)) {
            existing_plugins.push(Value::String(entry));
        }
    }

    settings.insert("plugins".to_string(), Value::Array(existing_plugins));

    let content = serde_json::to_string_pretty(&settings)?;
    fs::write(&path, content)?;

    Ok(())
}
