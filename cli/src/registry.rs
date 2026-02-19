use serde::Deserialize;

const MARKETPLACE_JSON: &str = include_str!("../../.claude-plugin/marketplace.json");

#[derive(Deserialize)]
pub struct Marketplace {
    pub plugins: Vec<Plugin>,
}

#[derive(Deserialize, Clone)]
pub struct Plugin {
    pub name: String,
    pub source: String,
    pub description: String,
}

pub fn load() -> Marketplace {
    serde_json::from_str(MARKETPLACE_JSON).expect("Failed to parse marketplace.json")
}
