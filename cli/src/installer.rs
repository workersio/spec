use serde_json::{json, Map, Value};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

use crate::registry::Plugin;

const GITHUB_REPO: &str = "workersio/spec";
const MARKETPLACE_NAME: &str = "workers-io";

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Scope {
    Project,
    User,
}

fn claude_home() -> PathBuf {
    std::env::var("HOME")
        .map(PathBuf::from)
        .expect("Failed to get HOME directory")
        .join(".claude")
}

fn plugins_dir() -> PathBuf {
    claude_home().join("plugins")
}

pub fn settings_path(scope: &Scope) -> PathBuf {
    match scope {
        Scope::Project => {
            let cwd = std::env::current_dir().expect("Failed to get current directory");
            cwd.join(".claude").join("settings.json")
        }
        Scope::User => claude_home().join("settings.json"),
    }
}

fn iso_now() -> String {
    let output = Command::new("date")
        .args(["-u", "+%Y-%m-%dT%H:%M:%S.000Z"])
        .output()
        .expect("Failed to get current timestamp");
    String::from_utf8_lossy(&output.stdout).trim().to_string()
}

fn read_json_map(path: &Path) -> Map<String, Value> {
    if path.exists() {
        let content = fs::read_to_string(path).unwrap_or_default();
        serde_json::from_str(&content).unwrap_or_default()
    } else {
        Map::new()
    }
}

fn write_json_map(path: &Path, data: &Map<String, Value>) -> std::io::Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let content = serde_json::to_string_pretty(data)?;
    fs::write(path, format!("{}\n", content))?;
    Ok(())
}

fn copy_dir_recursive(src: &Path, dst: &Path) -> std::io::Result<()> {
    fs::create_dir_all(dst)?;
    for entry in fs::read_dir(src)? {
        let entry = entry?;
        let src_path = entry.path();
        let dst_path = dst.join(entry.file_name());
        if src_path.is_dir() {
            copy_dir_recursive(&src_path, &dst_path)?;
        } else {
            fs::copy(&src_path, &dst_path)?;
        }
    }
    Ok(())
}

fn git_commit_sha() -> Option<String> {
    let marketplace_dir = plugins_dir().join("marketplaces").join(MARKETPLACE_NAME);
    Command::new("git")
        .args(["rev-parse", "HEAD"])
        .current_dir(&marketplace_dir)
        .output()
        .ok()
        .filter(|o| o.status.success())
        .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())
}

/// Step 1: Register the workers-io marketplace in known_marketplaces.json
fn register_marketplace() -> Result<(), String> {
    let path = plugins_dir().join("known_marketplaces.json");
    let mut marketplaces = read_json_map(&path);

    let install_location = plugins_dir()
        .join("marketplaces")
        .join(MARKETPLACE_NAME);

    marketplaces.insert(
        MARKETPLACE_NAME.to_string(),
        json!({
            "source": {
                "source": "github",
                "repo": GITHUB_REPO
            },
            "installLocation": install_location.to_string_lossy(),
            "lastUpdated": iso_now()
        }),
    );

    write_json_map(&path, &marketplaces)
        .map_err(|e| format!("Failed to write known_marketplaces.json: {}", e))
}

/// Step 2: Clone or update the marketplace repo
fn ensure_marketplace_repo() -> Result<(), String> {
    let marketplace_dir = plugins_dir()
        .join("marketplaces")
        .join(MARKETPLACE_NAME);

    if marketplace_dir.join(".git").exists() {
        let output = Command::new("git")
            .args(["pull", "--ff-only", "-q"])
            .current_dir(&marketplace_dir)
            .output()
            .map_err(|e| format!("Failed to run git pull: {}", e))?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            return Err(format!("git pull failed: {}", stderr));
        }
    } else {
        fs::create_dir_all(marketplace_dir.parent().unwrap())
            .map_err(|e| format!("Failed to create marketplaces directory: {}", e))?;

        let url = format!("https://github.com/{}.git", GITHUB_REPO);
        let output = Command::new("git")
            .args(["clone", "-q", &url, &marketplace_dir.to_string_lossy()])
            .output()
            .map_err(|e| format!("Failed to run git clone: {}", e))?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            return Err(format!("git clone failed: {}", stderr));
        }
    }

    Ok(())
}

/// Step 3: Copy plugin files from marketplace clone to cache
fn cache_plugin(plugin: &Plugin) -> Result<(PathBuf, String), String> {
    let marketplace_dir = plugins_dir()
        .join("marketplaces")
        .join(MARKETPLACE_NAME);
    let source = plugin.source.trim_start_matches("./");
    let plugin_source = marketplace_dir.join(source);

    let plugin_json_path = plugin_source.join(".claude-plugin").join("plugin.json");
    let plugin_json: Map<String, Value> = {
        let content = fs::read_to_string(&plugin_json_path)
            .map_err(|e| format!("Failed to read plugin.json: {}", e))?;
        serde_json::from_str(&content)
            .map_err(|e| format!("Failed to parse plugin.json: {}", e))?
    };

    let version = plugin_json
        .get("version")
        .and_then(|v| v.as_str())
        .unwrap_or("0.0.0")
        .to_string();

    let cache_dir = plugins_dir()
        .join("cache")
        .join(MARKETPLACE_NAME)
        .join(&plugin.name)
        .join(&version);

    if cache_dir.exists() {
        fs::remove_dir_all(&cache_dir)
            .map_err(|e| format!("Failed to clear existing cache: {}", e))?;
    }

    copy_dir_recursive(&plugin_source, &cache_dir)
        .map_err(|e| format!("Failed to copy plugin to cache: {}", e))?;

    Ok((cache_dir, version))
}

/// Step 4: Register plugin in installed_plugins.json
fn register_installed(
    plugin: &Plugin,
    install_path: &Path,
    version: &str,
    scope: &Scope,
) -> Result<(), String> {
    let path = plugins_dir().join("installed_plugins.json");
    let mut installed = read_json_map(&path);

    installed.entry("version").or_insert(json!(2));

    let plugins = installed
        .entry("plugins")
        .or_insert_with(|| json!({}))
        .as_object_mut()
        .expect("plugins should be an object");

    let key = format!("{}@{}", plugin.name, MARKETPLACE_NAME);
    let now = iso_now();

    let mut entry = json!({
        "scope": match scope {
            Scope::User => "user",
            Scope::Project => "project",
        },
        "installPath": install_path.to_string_lossy(),
        "version": version,
        "installedAt": &now,
        "lastUpdated": &now
    });

    if *scope == Scope::Project {
        let cwd = std::env::current_dir().expect("Failed to get current directory");
        entry.as_object_mut().unwrap().insert(
            "projectPath".to_string(),
            json!(cwd.to_string_lossy().into_owned()),
        );
    }

    if let Some(sha) = git_commit_sha() {
        entry
            .as_object_mut()
            .unwrap()
            .insert("gitCommitSha".to_string(), json!(sha));
    }

    plugins.insert(key, json!([entry]));

    write_json_map(&path, &installed)
        .map_err(|e| format!("Failed to write installed_plugins.json: {}", e))
}

/// Step 5: Enable plugin in settings.json via enabledPlugins
fn enable_plugin(plugin: &Plugin, scope: &Scope) -> Result<(), String> {
    let path = settings_path(scope);
    let mut settings = read_json_map(&path);

    let enabled = settings
        .entry("enabledPlugins")
        .or_insert_with(|| json!({}))
        .as_object_mut()
        .expect("enabledPlugins should be an object");

    let key = format!("{}@{}", plugin.name, MARKETPLACE_NAME);
    enabled.insert(key, json!(true));

    write_json_map(&path, &settings)
        .map_err(|e| format!("Failed to write settings.json: {}", e))
}

pub fn install(plugins: &[Plugin], scope: &Scope) -> Result<(), String> {
    // Step 1: Register marketplace source
    register_marketplace()?;

    // Step 2: Clone or update marketplace repo
    ensure_marketplace_repo()?;

    // Step 3-5: For each plugin, cache, register, and enable
    for plugin in plugins {
        let (install_path, version) = cache_plugin(plugin)?;
        register_installed(plugin, &install_path, &version, scope)?;
        enable_plugin(plugin, scope)?;
    }

    Ok(())
}
