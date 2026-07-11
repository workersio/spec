# workload-harness library

Product-agnostic workload modules. At init/scaffold time the skill copies this
directory into the target repo as `.workers/lib/`; workloads import from there
(`sys.path.insert` of the workload's own directory's parent, or a relative
import — the modules are single-file and dependency-free beyond the stdlib).

| Module | Strategy class | What it gives a workload |
|---|---|---|
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
