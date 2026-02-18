# workers-spec

Share Claude Code sessions as replayable specs.

## Install

```bash
npm install -g @workersio/spec
```

Or from source:

```bash
cargo install --git https://github.com/workersio/spec workers-spec-cli
```

## Usage

In Claude Code, share the current session:

```
/share
```

Run a shared spec:

```
/run <url>
```

## CLI Commands

| Command | Description |
|---|---|
| `workers-spec status` | Check server health |
| `workers-spec config` | View configuration |
| `workers-spec config --server-url <url>` | Point CLI at a custom server |
| `workers-spec config --reset` | Reset to default server |
| `workers-spec share <session_id>` | Share a session |
| `workers-spec run <url_or_id>` | Preview a spec |
| `workers-spec run <url_or_id> --full` | Output full spec content |

## Self-Hosting

[![Deploy to Cloudflare](https://deploy.workers.cloudflare.com/button)](https://deploy.workers.cloudflare.com/?url=https://github.com/workersio/spec/tree/main/worker)

After deploying, point your CLI at your instance:

```bash
workers-spec config --server-url https://your-worker.your-subdomain.workers.dev
```

To switch back to the default server:

```bash
workers-spec config --reset
```

## License

MIT
