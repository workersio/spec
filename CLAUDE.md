# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository

https://github.com/workersio/spec

## What This Project Does

workers-spec converts Claude Code session transcripts into reusable, shareable specifications. A session JSONL file is fed to Claude with a prompt template (`prompt.md`) that distills the session into a structured spec with YAML frontmatter. The spec is then uploaded to an API server and can be fetched/replayed later.

## Installation

```bash
# Via npm (downloads prebuilt binary + installs /share and /run slash commands)
bun install -g @workersio/spec

# Or from source
cargo install --git https://github.com/workersio/spec workers-spec-cli
```

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
```

## Architecture

### Workspace Structure (2 crates)

- **`crates/core`** (`workers-spec-core`) — Shared library. Spec YAML frontmatter parser (`spec_parser.rs`), session file locator (`transcript.rs`), and the prompt template (`PROMPT_TEMPLATE` embedded from `prompt.md` via `include_str!`).
- **`crates/cli`** (`workers-spec-cli`) — Clap-based CLI with subcommands:
  - `config [--server-url <url>] [--reset]` — view/update server URL in `~/.config/workers-spec/config.toml`
  - `share <session_id> [-w workspace]` — reads session JSONL, spawns `claude -p` to generate spec, POSTs to API, prints URL
  - `run <url_or_id> [--full]` — fetches spec from API; preview mode shows title/summary/sections, `--full` prints raw content
  - `status` — checks server health

### npm Package (root)

Node.js distribution wrapper (`package.json`, `bin/`, `commands/`). `postinstall` downloads the Rust binary from GitHub releases. Also installs `/share` and `/run` as Claude Code slash commands into `~/.claude/commands/`.

### Cloudflare Worker (backend)

`worker/` — TypeScript Cloudflare Worker with D1 (serverless SQLite). Routes: `POST /api/specs`, `GET /api/specs/{id}`, `GET /health`. Deployed at `specs.workers.io`. Self-hostable via "Deploy to Cloudflare" button.

### Key Data Flow

1. `share` command reads `~/.claude/projects/{normalized_cwd}/{session_id}.jsonl`
2. Injects transcript into `prompt.md` template (replaces `{transcript}`)
3. Spawns `claude -p` with the prompt to generate a structured spec
4. Worker parses frontmatter (title, description, tags) and stores in D1
5. `run` command fetches spec by ID and either previews or outputs full content

### CLI Configuration

- Config file: `~/.config/workers-spec/config.toml` (stores `api_url`)
- Default server: `https://specs.workers.io`
- Env override: `WORKERS_SPEC_API_URL`

### Spec Format

Specs use YAML frontmatter with required fields (`title`, `description`, `tags`) followed by markdown body with sections: Objective, Requirements (with WHEN/THEN scenarios), Methodology, Output Format, Quality Criteria. The full format is defined in `prompt.md`.
