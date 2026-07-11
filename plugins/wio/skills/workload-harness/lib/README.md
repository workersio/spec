# workload-harness library

Product-agnostic workload modules. At init/scaffold time the skill copies this
directory into the target repo as `.workers/lib/`; workloads import from there
(`sys.path.insert` of the workload's own directory's parent, or a relative
import — the modules are single-file and dependency-free beyond the stdlib).

v2 (usage-first) adds the scenario spine — `CONTRACT.md` in this directory is
the exact integration contract between these modules.

| Module | Strategy class | What it gives a workload |
|---|---|---|
| `frontmatter.py` | shared parser | Minimal YAML-subset frontmatter parse/dump/load for `.workers/` metadata (the guest has no PyYAML); loud `ValueError` with line numbers — a parse failure is never a silently-empty dict. |
| `scenario_gen.py` | v2 generation | The grammar sampler: `build_plan(meta, model, seed)` expands a scenario's cast into actors with seeded flow sequences and event timing (`PLAN` line); the **shrinker** (`shrink`: drop actors → flows → ops) for crystallizing reds; the `api-explorer` rarity sampler (`api_explorer_seq`, inverse-traffic weights). |
| `run_scenario.py` | v2 spine (executable) | THE runnable: one scenario file + one seed → build plan, load `flows/flows_<target>.py`, run actors (inline or interleaved), arm the scenario's event at crashclock-style timing, run every plane oracle, emit `SEED`/`PLAN`/`INVARIANT`/`VERDICT`, exit 0/1/3/44. `--redproof` plants an observation-channel violation and demands the oracles catch it (`ORACLE_SELFTEST`). |
| `personaledger.py` | universal oracle | Per-actor ledger: everything this actor was told succeeded is still true for it; nothing it was denied happened anyway. `acked`/`denied`/`observe` → `check_all` emits `INVARIANT ledger_<actor> …`; oracle strength scales with cast size. |
| `errorcontract.py` | universal oracle | Every failure is the *promised* failure: `expect(op)` classifies outcomes against the flow's `documented` map — undocumented internal errors and silent successes are reds. |
| `wallclock.py` | universal oracle | Declared per-step latency bounds (`bound(label, max_s)`); bounded-extra-delay violations are reds, not vibes. |
| `check.py` | v2 compiler | Copied to `.workers/check.py` at init: rules G1–G9 over the tree (format, model↔driver bijections, the G5 no-green-without-redproof law, the G8 usage-native module floor), `--status` (derived dispatcher row), `--emit` (compiled candidates header). |
| `crashclock.py` | fault-timing | Maps the runtime's sequential seed to a point in a *declared* fault-timing space (op-index kill, latency-window kill, phase straddle, multi-point kill/restart schedules) plus the fault primitives themselves: `kill_self_child`, `restart_dependency`, `hold_lock`. Every armed clock emits a `CLOCK` event line so sweep triage can bucket reds by timing point. |
| `durawatch.py` | universal oracle | Acked-durability watch: everything the product 200-acked goes into a manifest and is re-observed on a declared delay ladder (default `[0s, +30s, +75s]`); missing or mutated ⇒ `INVARIANT durability_watch_<rung> FAIL`. Survives process restarts between rungs (manifest persisted). Composes with crashclock. |
| `genlib.py` | input-generation | Seeded generator + differential harness core: a single integer seed fully determines a generated Program (Config + Ops over declared sweep axes); universal oracles (differential rows/error-class, integrity, panic, terminal-state, reopen-persistence); declarative known-divergence allowlist — suppression is never silent. |
| `interleave.py` | interleaving | Seed-driven ordering search over 2–3 concurrent actors: barriers + seeded release permutations, so sweeping seeds sweeps orderings instead of hand-freezing one. Selftest hook proves the oracle can go RED. |
| `turso_genfuzz.py` | (example) | Reference per-target adapter wiring `genlib` to a concrete CLI engine — copy this shape for a new target. |

Shared conventions all modules enforce:

- **Declared spaces, not magic constants** — a workload declares the axis being
  swept (timing space, sweep axes, actor pools); auditors see the search space.
- **Determinism** — same seed ⇒ same program/offsets/ordering, across processes.
- **Anti-vacuity floors** — a case that never armed its fault or acked too few
  effects is `VOID`, not green.
- **Selftest** — each oracle can plant a known violation and must go RED
  (`ORACLE_SELFTEST`), so a green run is evidence the oracle was live.

Tests: `test_<module>.py` beside each module; plain `python3 test_x.py`, no
framework needed.
