CREATE TABLE IF NOT EXISTS specs (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    step_count INTEGER NOT NULL DEFAULT 0,
    version TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
