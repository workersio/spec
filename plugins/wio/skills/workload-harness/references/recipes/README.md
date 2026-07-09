# Dependency-service recipes

A target's promises often live on surfaces that need a real dependency
(Postgres, a Kafka broker) inside the wio guest. These recipes make those
surfaces reachable instead of silently testing a fallback (e.g. SQLite) and
calling the area covered. **A promise that only exists on Postgres is not
covered by a SQLite run** — check the target's config-resolution defaults
before deciding a surface is exercised.

Conventions every recipe follows:

- **Vendored, not fetched at run time.** Copy the recipe into the repo's
  `.workers/` at init; `build.sh` compiles/installs whatever the recipe needs
  so runs are hermetic.
- **exit 44 = setup-block.** A recipe that cannot provide its service exits 44
  with a `setup-block:` line. Setup blockers are infrastructure findings, never
  product findings — record them, don't let them masquerade as green or red.
- **Restartable.** The service runs as a child the workload owns, so
  fault-timing workloads can stop/start it mid-run (see `lib/crashclock.py`
  `DependencyHandle` / `restart_dependency`) — dependency-outage timing is a
  first-class fault axis, not an accident.

## run-with-postgres.sh

Wraps a command with a throwaway Postgres: initdb into tmp, trust auth, waits
for ready, execs the command, tears down on exit. Env knobs: `WIO_PGDATA`,
`PGPORT`, `PGHOST_ADDR`, `PGPASSWORD`. Ships a uuid-ossp compatibility marker
for products that `CREATE EXTENSION "uuid-ossp"` but only use built-in
`gen_random_uuid()`. Requires postgres binaries in the guest image (exit 44
otherwise).

Usage: `.workers/run-with-postgres.sh python3 my_workload.py`

## kafka-broker/

Minimal in-memory Kafka-protocol broker (Go, `franz-go/pkg/kfake`) for guests
where a real broker is impractical. `build.sh` compiles it to a static binary
(`CGO_ENABLED=0 go build`); the workload starts it as a child process and can
kill/relaunch it for fault-timing runs. Flags: `-port` (default 9092),
`-partitions`.
