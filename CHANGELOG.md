# Changelog

All notable changes to `@workersio/skills` are tracked here.

## 0.6.0

- workload-harness: ship the product-agnostic workload library under the
  skill's `lib/` — `crashclock` (seed-swept fault timing), `durawatch`
  (acked-durability watch oracle), `genlib` (seeded generator + differential
  harness), `interleave` (seeded ordering search) — with test suites and an
  example per-target adapter.
- workload-harness: dependency-service recipes under `references/recipes/` —
  throwaway-Postgres wrapper and a minimal kfake Kafka broker — so
  Postgres-only / broker-only promise surfaces are reachable in the guest.
- workload-harness: **aim discipline** — the dispatcher may not self-stop
  while any above-threshold backlog row is un-attacked and rails remain.
- workload-harness: **universal oracle plane** defaults on every workload —
  liveness watchdog, terminal-state sweep, acked-durability watch, declared
  fault timing, async-parity drivers.
- workload-harness: **mapping-breadth floor** — every target module is inside
  an area's code loci or explicitly parked with a reason; gaps arm re-plan.
- workload-harness: init copies `lib/` and `recipes/` into `.workers/`.
- Sync wio plugin v0.5.0 from the dev box (workload-harness skill, critic
  backlog audit) — previously unpushed.

## 0.1.0

- Initial skill and plugin package.
- Added command modes: `scan`, `test`, `workload`, `review`, and `doctor`.
- Added Codex and Claude Code plugin metadata.
- Added optional subagents and hook reminders.
- Added testing reference library under `plugins/wio/skills/wio/references/`.
