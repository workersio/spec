# workers-spec

Convert Claude Code sessions into reusable, shareable agents.

workers-spec distills Claude Code conversations into agent files — the native subagent primitive. A session becomes an agent with a system prompt (role, behavior, rules, output format) that you can invoke with `@agent-name` in any future conversation.

Distributed as a Claude Code plugin — zero binaries, zero npm, native integration.

---

## Installation

### From the marketplace

```
/plugin marketplace add workersio/spec
/plugin install spec@workers-spec
```

### From a local clone

```bash
git clone https://github.com/workersio/spec.git
```

Then in Claude Code:

```
/plugin install /path/to/spec/plugins/spec
```

---

## Commands

These commands are available inside Claude Code after installing the plugin.

| Command | Description |
|---|---|
| `/spec:share` | Generate an agent from the current session and upload it. Returns a shareable URL. |
| `/spec:save` | Generate an agent from the current session and save it to `.claude/agents/`. |
| `/spec:save <url>` | Fetch a shared agent by URL or ID and save it locally to `.claude/agents/`. |

---

## Usage

### Share a session

In any Claude Code session, type:

```
/spec:share
```

This analyzes the conversation, generates an agent file, uploads it, and returns a shareable URL.

### Save locally

```
/spec:save
```

Generates an agent file and saves it to `.claude/agents/{name}.md` in the current directory. You can then invoke it with `@{name}`.

### Save from a shared URL

```
/spec:save https://spec.workers.io/s/abc123
```

Fetches the agent, saves it to `.claude/agents/`, and makes it available as `@{name}`.

You can also use a bare ID:

```
/spec:save abc123
```

---

## Configuration

| Setting | Default |
|---|---|
| API server | `https://spec.workers.io` |
| Env override | `WORKERS_SPEC_API_URL` |

Set a custom server URL via environment variable:

```bash
export WORKERS_SPEC_API_URL=https://your-worker.your-subdomain.workers.dev
```

---

## Self-Hosting

The backend is a Cloudflare Worker with D1 (serverless SQLite). You can deploy your own instance:

[![Deploy to Cloudflare](https://deploy.workers.cloudflare.com/button)](https://deploy.workers.cloudflare.com/?url=https://github.com/workersio/spec/tree/main/worker)

After deploying, set the environment variable to point at your instance:

```bash
export WORKERS_SPEC_API_URL=https://your-worker.your-subdomain.workers.dev
```

---

## Migrating from npm

If you previously installed `@workersio/spec` via npm:

1. Uninstall the npm package:

   ```bash
   npm uninstall -g @workersio/spec
   ```

2. Remove old slash commands (if present):

   ```bash
   rm -f ~/.claude/commands/share.md ~/.claude/commands/run.md ~/.claude/commands/save.md
   ```

3. Install the plugin using the instructions above.

The new commands are `/spec:share` and `/spec:save` (namespaced under the plugin).

---

## Architecture

```
plugins/spec/                    # Claude Code plugin
  .claude-plugin/plugin.json     # Plugin manifest
  skills/
    share/SKILL.md               # /spec:share — generate + upload agent
    save/SKILL.md                # /spec:save — generate + save locally (or fetch from URL)

worker/                          # Cloudflare Worker backend (D1)
  src/index.ts                   # API routes
  migrations/                    # D1 schema migrations
```

The plugin skills run inline in Claude Code — no binary needed. The `share` and `save` skills analyze the current conversation directly (no session file reading or subprocess spawning). The `save` skill also handles fetching agents from the API server via curl when given a URL argument.

---

## License

MIT
