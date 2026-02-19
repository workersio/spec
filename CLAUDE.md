# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository

https://github.com/workersio/spec

## What This Project Does

workers-spec converts Claude Code conversations into reusable, shareable agents. Distributed as a Claude Code plugin with two skills (`/spec:share`, `/spec:save`). Agents are uploaded to an API server and can be fetched/saved locally as agent files.

## Architecture

### Plugin (`plugins/spec/`)

A Claude Code plugin with two skills:

- **`skills/share/SKILL.md`** (`/spec:share`) — Analyzes the current conversation, generates an agent file, uploads it via `curl POST` to the API server, and returns a shareable URL.
- **`skills/save/SKILL.md`** (`/spec:save`) — Dual-mode: with no args, generates an agent file from the conversation and saves to `.claude/agents/{slug}.md`. With a URL or ID arg, fetches from the API and saves locally as an agent file.

The skills embed the prompt template (agent generation instructions) directly in the SKILL.md files. Since skills run inline in Claude Code, they analyze the conversation context directly — no session file reading or subprocess spawning needed.

**Plugin manifest**: `plugins/spec/.claude-plugin/plugin.json`
**Marketplace catalog**: `.claude-plugin/marketplace.json` (repo root)

### Cloudflare Worker (`worker/`)

TypeScript Cloudflare Worker with D1 (serverless SQLite). Routes: `POST /api/specs`, `GET /api/specs/{id}`, `GET /health`. Deployed at `spec.workers.io`. Self-hostable via "Deploy to Cloudflare" button.

```bash
# Worker dev/deploy (from worker/ directory)
cd worker && bun run dev      # local dev server
cd worker && bun run deploy   # applies D1 migrations + deploys
```

### Key Data Flow

1. `/spec:share` or `/spec:save` analyzes the current conversation inline
2. Generates an agent file with YAML frontmatter (name, description, tools, model) + system prompt body
3. `/spec:share`: uploads via `curl POST` to API, worker parses frontmatter and stores in D1, returns URL
4. `/spec:save`: writes agent file to `.claude/agents/{name}.md` locally
5. `/spec:save <url>`: fetches from API via `curl GET`, converts legacy format if needed, saves to `.claude/agents/{name}.md`

### Configuration

- Default server: `https://spec.workers.io`
- Env override: `WORKERS_SPEC_API_URL`

### Agent File Format

Agent files use YAML frontmatter with required fields (`name`, `description`, `tools`, `model`) followed by a system prompt body with sections: role description, Behavior (numbered steps), Rules (bullet list), Output format. The full format is defined in each skill's SKILL.md.
