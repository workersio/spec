# workers-spec

Share Claude Code sessions as replayable specs.

workers-spec converts Claude Code session transcripts into structured, shareable specifications. A session is distilled into a spec with metadata (title, description, tags) and organized sections, then uploaded to an API server where others can fetch and replay it.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Getting Started](#getting-started)
- [Slash Commands](#slash-commands)
- [CLI Reference](#cli-reference)
- [Configuration](#configuration)
- [Self-Hosting](#self-hosting)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## Prerequisites

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed and available in your PATH
- Node.js / npm (for the recommended install method)
- macOS (x86_64 or ARM) or Linux (x86_64 or ARM)

---

## Installation

### From npm (recommended)

```bash
npm install -g @workersio/spec
```

This downloads a prebuilt binary and installs the `/share`, `/run`, and `/save` slash commands into `~/.claude/commands/`.

The binary is fetched on first use if it wasn't downloaded during install.

### From source

Requires [Rust](https://rustup.rs/) toolchain:

```bash
cargo install --git https://github.com/workersio/spec workers-spec-cli
```

Note: Building from source does not install the slash commands automatically. Run `workers-spec init` after installing to set them up.

---

## Getting Started

1. **Install the package:**

   ```bash
   npm install -g @workersio/spec
   ```

2. **Verify the installation:**

   ```bash
   workers-spec status
   ```

   You should see `Health: OK` if everything is working.

3. **Share a session** -- open Claude Code in any project and type:

   ```
   /share
   ```

   This generates a spec from your current session and returns a shareable URL.

4. **Run a shared spec:**

   ```
   /run <url>
   ```

   This fetches the spec, shows a preview, and asks for confirmation before executing.

---

## Slash Commands

These commands are available inside Claude Code after installation.

| Command | Description |
|---|---|
| `/share` | Generate a spec from the current session and upload it. Returns a shareable URL. |
| `/run <url>` | Fetch a shared spec, preview it, and execute it after confirmation. |
| `/save` | Generate a spec from the current session and save it locally to `.spec/`. |

---

## CLI Reference

The `workers-spec` binary can also be used directly from the terminal.

### `share`

```bash
workers-spec share <session_id> [-w <workspace>]
```

Reads a session transcript, generates a spec via Claude, and uploads it. Prints the resulting URL.

- `<session_id>` -- the Claude Code session ID
- `-w <workspace>` -- optional workspace path override

### `run`

```bash
workers-spec run <url_or_id> [--full]
```

Fetches a spec from the server.

- Without `--full` -- prints a preview (title, description, sections)
- With `--full` -- prints the complete spec content

Accepts full URLs (`https://specs.workers.io/s/abc123`) or bare IDs (`abc123`).

### `save`

```bash
workers-spec save <session_id> [-w <workspace>]
```

Same as `share`, but saves the generated spec to `.spec/` in the current directory instead of uploading.

### `config`

```bash
workers-spec config                        # View current configuration
workers-spec config --server-url <url>     # Set a custom server URL
workers-spec config --reset                # Reset to the default server
```

### `status`

```bash
workers-spec status
```

Checks connectivity to the configured API server.

### `init`

```bash
workers-spec init
```

Runs the setup wizard: configures the server URL and installs slash commands into `~/.claude/commands/`.

---

## Configuration

| Setting | Location |
|---|---|
| Config file | `~/.config/workers-spec/config.toml` |
| Default server | `https://spec.workers.io` |
| Env override | `WORKERS_SPEC_API_URL` |

The environment variable takes precedence over the config file.

---

## Self-Hosting

The backend is a Cloudflare Worker with D1 (serverless SQLite). You can deploy your own instance:

[![Deploy to Cloudflare](https://deploy.workers.cloudflare.com/button)](https://deploy.workers.cloudflare.com/?url=https://github.com/workersio/spec/tree/main/worker)

After deploying, point your CLI at your instance:

```bash
workers-spec config --server-url https://your-worker.your-subdomain.workers.dev
```

To switch back to the default server:

```bash
workers-spec config --reset
```

---

## Troubleshooting

### "Failed to spawn claude. Is Claude CLI installed?"

The `workers-spec share` and `workers-spec save` commands require the Claude Code CLI (`claude`) to be in your PATH. Verify it is installed:

```bash
claude --version
```

If not installed, see the [Claude Code documentation](https://docs.anthropic.com/en/docs/claude-code).

### "Session file not found in any project directory"

The CLI looks for session transcripts in `~/.claude/projects/`. This error means the session ID you provided does not match any `.jsonl` file in that directory tree.

- Make sure you are passing a valid session ID.
- If using `/share` inside Claude Code, the session ID is provided automatically via `$CLAUDE_SESSION_ID`.
- If running manually, check that the session file exists:

  ```bash
  ls ~/.claude/projects/*/*.jsonl
  ```

### "Spec generation timed out (5 min limit)"

Spec generation is capped at 5 minutes. This can happen with very large session transcripts. There is no workaround other than sharing shorter sessions.

### "Health: unreachable"

The CLI cannot connect to the API server. Check:

1. Your internet connection.
2. The configured server URL:

   ```bash
   workers-spec config
   ```

3. If self-hosting, verify your Cloudflare Worker is deployed and running.

### "API returned {status}: {body}"

The API server returned an error. Common causes:

- **404** on `run` -- the spec ID does not exist or has been deleted.
- **500** -- server-side error. If using the default server, try again later. If self-hosting, check your Worker logs.

### Binary not found or download fails

If the prebuilt binary was not downloaded during `npm install`, it will be fetched on first use. If that also fails (e.g., no network, GitHub rate limiting):

- Retry the command after a few minutes.
- Install from source as a fallback:

  ```bash
  cargo install --git https://github.com/workersio/spec workers-spec-cli
  ```

### "Unsupported architecture" or "Unsupported platform"

Prebuilt binaries are available for:

- macOS (x86_64, ARM/Apple Silicon)
- Linux (x86_64, ARM)

Windows is not supported. On unsupported platforms, build from source with Cargo.

### Slash commands not appearing in Claude Code

The installer copies command files to `~/.claude/commands/`. If they are missing:

1. Re-run the setup:

   ```bash
   workers-spec init
   ```

2. Or reinstall the npm package:

   ```bash
   npm install -g @workersio/spec
   ```

3. Restart Claude Code after installing.

### Enabling debug logs

Set the `RUST_LOG` environment variable for verbose output:

```bash
RUST_LOG=debug workers-spec share <session_id>
```

---

## License

MIT
