# Changelog

All notable changes to `@workersio/skills` are tracked here.

## 0.2.0

- Added a deterministic, fail-closed model critic and made its current clean,
  content-stamped report a required boundary before future model ratification.
  The first mechanical rule flags entry-state assertions or raises before an
  atom's first checkpoint; findings have no waiver path.
- Rebuilt `workload-harness` as a thin model-authoring skill over the public
  WIO SDK and CLI contracts. It now authors cited Python or TypeScript atoms,
  requires explicit operation-local `creates`/`consumes`/`plain` roles, and
  asks for human ratification before execution.
- Added an idempotent three-zone `.workers/` scaffold and a deterministic,
  fail-closed format-1 manifest checker. Removed the embedded scenario
  generator, ranker, oracle library, recipes, dispatcher, and stop logic; those
  responsibilities belong to the installed deterministic product.
- Added Codex skill UI metadata, aligned Codex and Claude plugin metadata on
  the 0.2 release line, and removed the unsupported Codex plugin hook field.

## 0.1.3

- workload-harness: **build-first doctrine** (the headline; graded-row
  post-mortems: sessions self-stopped with ~95% of case budget unspent while
  demoting corridors as "unreachable") — reach engineering is producible
  work: a reachability-blocked corridor converts into an infrastructure
  candidate scored by the weight it unlocks; demotion requires climbing the
  infra-check ladder (in-process driver → dependency-fault shim → service
  recipe/guest-binary inventory → in-process approximation) and recording
  `infra-check:` on the row; the dispatcher's stop row refuses
  coverage-exhausted while an infra-unlockable corridor stands
  (producer.md §Build-first, SKILL.md row 1, critic briefs).
- workload-harness: **prose rules become mechanical gates** — async parity
  is now an executor done-gate and a test-reviewer REDO check (a sync-only
  driver on a dual-form API needs a recorded `async:` reason); the
  mapping-breadth floor must be written as a `floor: … / <n> orphans` line
  in loop-state.md and row 1 requires `0 orphans`. Both rules existed as
  prose and were skipped silently in graded runs.
- workload-harness: **body-entry ledger** joins the universal oracle plane —
  checkpointed steps replay when a body re-executes, so step-effect counts
  are structurally blind to body re-execution; invocation-dedup oracles must
  count body entries (executor.md, test-reviewer brief).
- workload-harness: **dependency-fault shims** — in-process faults (transient
  DB error, slow call, held lock) injected by wrapping the SUT's own
  client/engine seam at crashclock-derived timing; the shim rung precedes any
  reachability demotion (executor.md, SKILL.md oracle plane).

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
