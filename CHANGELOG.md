# Changelog

All notable changes to `@workersio/skills` are tracked here.

## 0.1.2

- workload-harness: **self-contained subagent briefs** — scout and critic
  briefs now ship inside the skill
  (`references/briefs/{candidate-scout,strategy-critic,test-reviewer}.md`)
  with the methodology they need embedded (distilled from the wio
  references: workload-modeling, risk-based-testing, test-level-selection,
  oracles/fixtures/doubles) and a hard confinement rule: a dispatched
  subagent reads only the target working tree plus this skill's directory.
- workload-harness: producer.md / critics.md / SKILL.md now dispatch generic
  read-only subagents on the embedded briefs by default; the installed
  `wio:wio-*` plugin agents remain an acceptable equivalent on normal plugin
  installs only — from a standalone copy of the skill their definitions read
  the sibling `wio` skill's reference library, i.e. outside the copy (the
  lab row-3 taint, ledger DEC-017). The `wio` skill's own agents and
  references are unchanged.

## 0.1.1

> Versioning policy: `0.1.x` is the internal iteration line — expect many
> small bumps. `0.2.0` is reserved for the first release we share publicly.
> (Iterations previously labeled 0.4.x/0.5.0 on the dev box collapse into
> this line; run records pin skill identity by git sha, not version label.)

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
- Sync the workload-harness skill and critic backlog audit from the dev box
  — previously unpushed.

## 0.1.0

- Initial skill and plugin package.
- Added command modes: `scan`, `test`, `workload`, `review`, and `doctor`.
- Added Codex and Claude Code plugin metadata.
- Added optional subagents and hook reminders.
- Added testing reference library under `plugins/wio/skills/wio/references/`.
