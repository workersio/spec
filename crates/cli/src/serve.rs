use axum::{
    extract::{Path, State},
    http::StatusCode,
    routing::{get, post},
    Json, Router,
};
use rusqlite::{params, Connection};
use serde::{Deserialize, Serialize};
use std::sync::{Arc, Mutex};
use tower_http::cors::CorsLayer;
use tracing::info;
use workers_spec_core::parse_spec;

// --- Store ---

pub struct Store {
    conn: Mutex<Connection>,
}

#[derive(Debug, Serialize)]
pub struct SpecRecord {
    pub id: String,
    pub content: String,
    pub title: String,
    pub summary: String,
    pub step_count: i64,
    pub version: String,
    pub created_at: String,
}

impl Store {
    pub fn new(database_path: &str) -> anyhow::Result<Self> {
        let conn = Connection::open(database_path)?;
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS specs (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                step_count INTEGER NOT NULL DEFAULT 0,
                version TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )",
        )?;
        Ok(Self {
            conn: Mutex::new(conn),
        })
    }

    pub fn insert(
        &self,
        id: &str,
        content: &str,
        title: &str,
        summary: &str,
        step_count: i64,
        version: &str,
    ) -> anyhow::Result<()> {
        let conn = self.conn.lock().unwrap();
        conn.execute(
            "INSERT INTO specs (id, content, title, summary, step_count, version) VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
            params![id, content, title, summary, step_count, version],
        )?;
        Ok(())
    }

    pub fn get(&self, id: &str) -> anyhow::Result<Option<SpecRecord>> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = conn.prepare(
            "SELECT id, content, title, summary, step_count, version, created_at FROM specs WHERE id = ?1",
        )?;
        let mut rows = stmt.query(params![id])?;
        match rows.next()? {
            Some(row) => Ok(Some(SpecRecord {
                id: row.get(0)?,
                content: row.get(1)?,
                title: row.get(2)?,
                summary: row.get(3)?,
                step_count: row.get(4)?,
                version: row.get(5)?,
                created_at: row.get(6)?,
            })),
            None => Ok(None),
        }
    }
}

// --- HTTP types ---

struct AppState {
    store: Store,
    base_url: String,
}

#[derive(Deserialize)]
struct CreateSpecRequest {
    content: String,
    #[serde(default)]
    version: Option<String>,
}

#[derive(Serialize, Deserialize)]
struct CreateSpecResponse {
    id: String,
    url: String,
}

#[derive(Serialize, Deserialize)]
struct SpecResponse {
    id: String,
    content: String,
    title: String,
    summary: String,
    step_count: i64,
    version: String,
    created_at: String,
}

#[derive(Serialize)]
struct ErrorResponse {
    error: String,
}

const MAX_CONTENT_SIZE: usize = 500 * 1024;

fn count_steps(content: &str) -> i64 {
    content
        .lines()
        .filter(|l| {
            let t = l.trim();
            t.len() > 2 && t.as_bytes()[0].is_ascii_digit() && t.contains(". ")
        })
        .count() as i64
}

// --- Handlers ---

async fn create_spec(
    State(state): State<Arc<AppState>>,
    Json(payload): Json<CreateSpecRequest>,
) -> Result<(StatusCode, Json<CreateSpecResponse>), (StatusCode, Json<ErrorResponse>)> {
    if payload.content.is_empty() {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(ErrorResponse {
                error: "content must not be empty".to_string(),
            }),
        ));
    }

    if payload.content.len() > MAX_CONTENT_SIZE {
        return Err((
            StatusCode::PAYLOAD_TOO_LARGE,
            Json(ErrorResponse {
                error: format!("content exceeds maximum size of {} bytes", MAX_CONTENT_SIZE),
            }),
        ));
    }

    let parsed = parse_spec(&payload.content);
    let id = nanoid::nanoid!(21);
    let step_count = count_steps(&payload.content);
    let version = payload.version.as_deref().unwrap_or("");

    state
        .store
        .insert(&id, &payload.content, &parsed.title, &parsed.description, step_count, version)
        .map_err(|e| {
            (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(ErrorResponse {
                    error: format!("failed to store spec: {e}"),
                }),
            )
        })?;

    let url = format!("{}/s/{}", state.base_url, id);
    info!("Created spec id={} title={:?} steps={}", id, parsed.title, step_count);

    Ok((StatusCode::CREATED, Json(CreateSpecResponse { id, url })))
}

async fn get_spec(
    State(state): State<Arc<AppState>>,
    Path(id): Path<String>,
) -> Result<Json<SpecResponse>, (StatusCode, Json<ErrorResponse>)> {
    let record = state.store.get(&id).map_err(|e| {
        (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(ErrorResponse {
                error: format!("database error: {e}"),
            }),
        )
    })?;

    match record {
        Some(r) => Ok(Json(SpecResponse {
            id: r.id,
            content: r.content,
            title: r.title,
            summary: r.summary,
            step_count: r.step_count,
            version: r.version,
            created_at: r.created_at,
        })),
        None => Err((
            StatusCode::NOT_FOUND,
            Json(ErrorResponse {
                error: "spec not found".to_string(),
            }),
        )),
    }
}

async fn health() -> Json<serde_json::Value> {
    Json(serde_json::json!({ "status": "ok" }))
}

// --- Public entry point ---

pub async fn run(port: u16, database_path: &str) -> anyhow::Result<()> {
    let base_url = std::env::var("BASE_URL")
        .unwrap_or_else(|_| format!("http://localhost:{port}"));

    let store = Store::new(database_path)?;
    info!("Database initialized at {}", database_path);

    let state = Arc::new(AppState { store, base_url });

    let app = Router::new()
        .route("/api/specs", post(create_spec))
        .route("/api/specs/{id}", get(get_spec))
        .route("/health", get(health))
        .layer(CorsLayer::permissive())
        .with_state(state);

    let listener = tokio::net::TcpListener::bind(("0.0.0.0", port)).await?;
    info!("Server listening on 0.0.0.0:{}", port);
    axum::serve(listener, app).await?;

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::body::Body;
    use http_body_util::BodyExt;
    use tower::ServiceExt;

    fn test_app() -> Router {
        let store = Store::new(":memory:").unwrap();
        let state = Arc::new(AppState {
            store,
            base_url: "http://localhost:3000".to_string(),
        });

        Router::new()
            .route("/api/specs", post(create_spec))
            .route("/api/specs/{id}", get(get_spec))
            .route("/health", get(health))
            .with_state(state)
    }

    #[tokio::test]
    async fn test_health() {
        let app = test_app();
        let req = axum::http::Request::builder()
            .uri("/health")
            .body(Body::empty())
            .unwrap();

        let resp = app.oneshot(req).await.unwrap();
        assert_eq!(resp.status(), StatusCode::OK);
    }

    #[tokio::test]
    async fn test_create_and_get_spec() {
        let app = test_app();

        let body = serde_json::json!({
            "content": "---\ntitle: Test Spec\ndescription: A test\ntags: [\"rust\"]\n---\n\n## Objective\nTest.\n\n## Methodology\n\n1. First step\n2. Second step",
            "version": "0.1.0"
        });

        let req = axum::http::Request::builder()
            .method("POST")
            .uri("/api/specs")
            .header("content-type", "application/json")
            .body(Body::from(serde_json::to_string(&body).unwrap()))
            .unwrap();

        let resp = app.clone().oneshot(req).await.unwrap();
        assert_eq!(resp.status(), StatusCode::CREATED);

        let body_bytes = resp.into_body().collect().await.unwrap().to_bytes();
        let created: CreateSpecResponse = serde_json::from_slice(&body_bytes).unwrap();
        assert!(!created.id.is_empty());
        assert!(created.url.contains(&created.id));

        let req = axum::http::Request::builder()
            .uri(format!("/api/specs/{}", created.id))
            .body(Body::empty())
            .unwrap();

        let resp = app.oneshot(req).await.unwrap();
        assert_eq!(resp.status(), StatusCode::OK);

        let body_bytes = resp.into_body().collect().await.unwrap().to_bytes();
        let fetched: SpecResponse = serde_json::from_slice(&body_bytes).unwrap();
        assert_eq!(fetched.id, created.id);
        assert_eq!(fetched.title, "Test Spec");
        assert_eq!(fetched.summary, "A test");
        assert_eq!(fetched.step_count, 2);
    }

    #[tokio::test]
    async fn test_get_not_found() {
        let app = test_app();
        let req = axum::http::Request::builder()
            .uri("/api/specs/nonexistent")
            .body(Body::empty())
            .unwrap();

        let resp = app.oneshot(req).await.unwrap();
        assert_eq!(resp.status(), StatusCode::NOT_FOUND);
    }

    #[tokio::test]
    async fn test_create_empty_content() {
        let app = test_app();
        let body = serde_json::json!({ "content": "" });

        let req = axum::http::Request::builder()
            .method("POST")
            .uri("/api/specs")
            .header("content-type", "application/json")
            .body(Body::from(serde_json::to_string(&body).unwrap()))
            .unwrap();

        let resp = app.oneshot(req).await.unwrap();
        assert_eq!(resp.status(), StatusCode::BAD_REQUEST);
    }

    #[tokio::test]
    async fn test_create_oversized_content() {
        let app = test_app();
        let large_content = "x".repeat(MAX_CONTENT_SIZE + 1);
        let body = serde_json::json!({ "content": large_content });

        let req = axum::http::Request::builder()
            .method("POST")
            .uri("/api/specs")
            .header("content-type", "application/json")
            .body(Body::from(serde_json::to_string(&body).unwrap()))
            .unwrap();

        let resp = app.oneshot(req).await.unwrap();
        assert_eq!(resp.status(), StatusCode::PAYLOAD_TOO_LARGE);
    }

    #[test]
    fn test_count_steps() {
        assert_eq!(count_steps("1. First\n2. Second\n3. Third"), 3);
        assert_eq!(count_steps("No steps here"), 0);
        assert_eq!(count_steps("  1. Indented step\n  2. Another"), 2);
    }

    #[test]
    fn test_store_insert_and_get() {
        let store = Store::new(":memory:").unwrap();
        store
            .insert("abc123", "# Test spec\n\n1. Step one\n2. Step two", "Test Title", "A test spec", 2, "0.1.0")
            .unwrap();

        let record = store.get("abc123").unwrap().unwrap();
        assert_eq!(record.id, "abc123");
        assert_eq!(record.title, "Test Title");
        assert_eq!(record.summary, "A test spec");
        assert_eq!(record.step_count, 2);
        assert_eq!(record.version, "0.1.0");
    }

    #[test]
    fn test_store_get_not_found() {
        let store = Store::new(":memory:").unwrap();
        assert!(store.get("nonexistent").unwrap().is_none());
    }

    #[test]
    fn test_store_duplicate_id_fails() {
        let store = Store::new(":memory:").unwrap();
        store.insert("dup", "c1", "t1", "s1", 0, "0.1.0").unwrap();
        assert!(store.insert("dup", "c2", "t2", "s2", 0, "0.1.0").is_err());
    }
}
