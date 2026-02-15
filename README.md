# workers-spec

Share Claude Code sessions as replayable specs.

## Install

```bash
npm install -g workers-spec
```

Or from source:

```bash
cargo install --git https://github.com/workersio/spec workers-spec-cli
```

## Usage

Start the local server:

```bash
workers-spec start
```

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
| `workers-spec start` | Start the local spec server |
| `workers-spec stop` | Stop the local spec server |
| `workers-spec status` | Check server status |
| `workers-spec config` | View configuration |
| `workers-spec config --server-url <url>` | Point CLI at a remote server |
| `workers-spec config --reset` | Reset to local server |
| `workers-spec share <session_id>` | Share a session |
| `workers-spec run <url_or_id>` | Preview a spec |
| `workers-spec run <url_or_id> --full` | Output full spec content |

## Deploy to a VPS

### 1. Build and run with Docker

```bash
git clone https://github.com/workersio/spec.git
cd spec
docker build -t workers-spec .

docker run -d --name workers-spec --restart unless-stopped \
  -p 3005:3005 \
  -e BASE_URL=http://YOUR_IP:3005 \
  -v specs-data:/data \
  workers-spec
```

Replace `YOUR_IP` with your server's IP or domain.

### 2. Point your CLI at the server

```bash
workers-spec config --server-url http://YOUR_IP:3005
```

Now `/share` uploads specs to your server and `/run` fetches from it.

### 3. Verify

```bash
workers-spec status
```

## License

MIT
