# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository

https://github.com/workersio/spec

## What This Project Does

workers-spec converts Claude Code session transcripts into reusable, shareable specifications. A session JSONL file is fed to Claude with a prompt template (`prompt.md`) that distills the session into a structured spec with YAML frontmatter. The spec is then uploaded to an API server and can be fetched/replayed later.

## Build & Test Commands

```bash
# Build all crates
cargo build

# Build release (optimized for size: opt-level=z, LTO, stripped)
cargo build --release

# Run tests for all crates
cargo test

# Run tests for a single crate
cargo test -p workers-spec-core
cargo test -p workers-spec-cli

# Run a single test by name
cargo test -p workers-spec-core test_parse_full_spec

# Run the CLI
cargo run -p workers-spec-cli -- <subcommand>

# Worker dev/deploy (from worker/ directory)
cd worker && bun run dev      # local dev server
cd worker && bun run deploy   # applies D1 migrations + deploys
```

## Architecture

### Workspace Structure (2 crates)

- **`crates/core`** (`workers-spec-core`) — Shared library. Spec YAML frontmatter parser (`spec_parser.rs`), session file locator (`transcript.rs`), and the prompt template (`PROMPT_TEMPLATE` embedded from `prompt.md` via `include_str!`).
- **`crates/cli`** (`workers-spec-cli`) — Clap-based CLI with subcommands:
  - `share <session_id> [-w workspace]` — generates spec from session, POSTs to API, prints URL
  - `save <session_id> [-w workspace]` — generates spec from session, saves locally to `.spec/`
  - `run <url_or_id> [--full]` — fetches spec from API; preview mode shows title/summary/sections, `--full` prints raw content
  - `config [--server-url <url>] [--reset]` — view/update server URL in `~/.config/workers-spec/config.toml`
  - `init` — interactive setup wizard (server URL, command installation)
  - `status` — checks server health

### Spec Generation Pipeline (`generate.rs`)

The `share` and `save` commands both use `generate_spec()` in `generate.rs` as their core:
1. `find_session_file()` locates `~/.claude/projects/{normalized_cwd}/{session_id}.jsonl`
2. Transcript content replaces `{transcript}` in `PROMPT_TEMPLATE`
3. Spawns `claude -p` with the filled prompt (300s timeout)
4. Returns the generated spec string

### npm Package (root)

Distribution wrapper (`package.json`, `bin/`, `commands/`). `bin/cli.sh` resolves the Rust binary via a three-stage fallback: vendor directory → PATH lookup → GitHub releases download. `bin/postinstall.sh` installs `/share`, `/run`, and `/save` as Claude Code slash commands into `~/.claude/commands/`.

### Cloudflare Worker (backend)

`worker/` — TypeScript Cloudflare Worker with D1 (serverless SQLite). Routes: `POST /api/specs`, `GET /api/specs/{id}`, `GET /health`. Deployed at `spec.workers.io`. Self-hostable via "Deploy to Cloudflare" button. The worker has its own YAML frontmatter parser that mirrors the Rust one in `spec_parser.rs`.

### Key Data Flow

1. `share`/`save` reads `~/.claude/projects/{normalized_cwd}/{session_id}.jsonl`
2. Injects transcript into `prompt.md` template (replaces `{transcript}`)
3. Spawns `claude -p` with the prompt to generate a structured spec
4. `share`: POSTs spec to API, worker parses frontmatter and stores in D1, returns URL
5. `save`: Parses spec title, slugifies it, writes to `.spec/{slug}.md`
6. `run`: Fetches spec by ID and either previews or outputs full content

### CLI Configuration

- Config file: `~/.config/workers-spec/config.toml` (stores `api_url`)
- Default server: `https://spec.workers.io`
- Env override: `WORKERS_SPEC_API_URL`

### Spec Format

Specs use YAML frontmatter with required fields (`title`, `description`, `tags`) followed by markdown body with sections: Objective, Requirements (with WHEN/THEN scenarios), Methodology, Output Format, Quality Criteria. The full format is defined in `prompt.md`.
