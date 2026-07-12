# Executor episodes — run one scenario; crystallize reds

The executor owns flow-driver code, run evidence, and the mechanical result
fields of exactly **one** scenario per episode. It never edits the usage
model — a model gap bounces the scenario back (`status: blocked`, `reason:`
in the prose, row-4 trigger).

## The episode, step by step

1. **Pick** the next `status: ready` scenario (lowest rung first per flow;
   a flow's L0 before its L1). Mark it in-flight in `journal.md`
   (`status: running` line), one at a time.
2. **Drivers exist?** Every flow key in the scenario must have a driver in
   `flows/flows_<target>.py` (`check.py` G2). Missing driver = write it now:
   the flow's steps from the model prose, acks/denials into `ctx.ledger`,
   documented errors declared in `documented`, latency bounds in `bounds`,
   `ctx.step(label)` at every point where another actor's interleaving could
   matter. Drivers are product-specific; the spine is not — never fork
   `lib/` code into a driver.
3. **Probe** (one seed, tiny): `<runner> .workers/lib/run_scenario.py
   .workers/scenarios/<key>.md --seed 1` locally first when possible, then as
   a depth-1 wio draft. Setup-blocks (exit 44) are infra work, not verdicts —
   fix the recipe/build, or bounce with the block recorded.
4. **Red-proof — before any trusted green** (G5): a depth-1 draft run with
   `--redproof` appended to the command. `run_scenario` picks one oracle
   channel by seed and corrupts its *observation channel only*; the run must
   end `ORACLE_SELFTEST PASS` (exit 0 — the planted violation was caught).
   Record the run id in `redproof:`. An `ORACLE_SELFTEST FAIL` means the
   oracle is dead: fix the oracle, never proceed to depth on a dead oracle.
5. **The sweep**: `wio simulate create <project> --command "<runner>
   .workers/lib/run_scenario.py .workers/scenarios/<key>.md" --depth <depth>`
   (no `--exploration` — this lane is draft-only). Poll `wio workloads ls`;
   triage failures by their `SEED`/`PLAN`/`INVARIANT` lines
   (`wio workloads logs <id>`).
6. **Verdict** (write the mechanical fields):
   - Any run with an `INVARIANT … FAIL` line → `result: finding`,
     `replay: {run: <id>, seed: <n>}`, `status: done`. Row 3 crystallizes
     next cycle — do not start another scenario first.
   - All green (with red-proof recorded) → `result: green`, `status: done`.
   - VOIDs → `result: void` + one shot at fixing vacuity (depth too shallow,
     event never fired, flows recorded nothing) before `done`.
   - Infrastructure wall → `status: blocked` + reason.
7. **Evidence** in the scenario prose: run ids, red seed(s), one-line
   analysis. Append the episode line to `journal.md`, run `check.py` (must
   exit 0), commit the episode's files together (one prepare cycle per
   batch, not per file).

Discipline carried from v1, verbatim: reward RED; a red is an emitted
`INVARIANT <id> <name> FAIL` line, never a bare nonzero exit; setup failures
are not findings; never weaken an oracle to make a scenario pass.

**Modality is load-bearing (G10).** The scenario's `modality:` names which
API variant the drivers must exercise — `ctx.modality` carries it into every
driver (`sync` | `async` | `threaded`). A driver drives the *declared*
variant: for `async`, the flow's steps call the product's async surface (the
driver may own a private event loop per actor); for `threaded`, the actor
calls the sync surface from worker threads it spawns. Silently running the
sync path under an `async` scenario is oracle fraud — if the driver cannot
honor the declared modality, bounce the scenario (`status: blocked`, model
gap) rather than fake it. The red-proof and all oracle channels are
modality-agnostic; only the calls into the SUT change.

## Crystallize (dispatcher row 3)

A raw composite red is a *discovery*, not yet a finding. Crystallizing makes
it minimal, attributable, and replayable:

1. **Shrink**: `scenario_gen.shrink` walks candidate smaller plans (drop
   actors → drop flows → shorten ops → lower depth). Re-run each candidate
   (draft, pinned `--seed`); keep the smallest still-red shape. Record the
   shrink path in the finding.
2. **Re-confirm**: one fresh draft run of the minimal shape; its run id +
   seed become `replay:`.
3. **Test-reviewer gate** ([critics.md](critics.md)): real invariant
   violation or oracle bug? user-meaningful? story updated to the minimal
   shape?
4. **Write `findings/<key>-<n>.md`** (scenario-format.md §findings):
   severity by the interception-weight scale, minimized shape, replay
   recipe, evidence. `status: held` — filing is the human's decision, never
   the loop's.
5. If the same underlying bug already has a finding, extend that file
   (additional witness) instead of minting a duplicate.

## Writing drivers well (the craft notes)

- The ledger is the oracle. Every SUT call that *tells the actor something*
  ends in `ctx.ledger.acked(...)` or `ctx.ledger.denied(...)`; every
  end-of-flow verification re-reads the world into `ctx.ledger.observe(...)`.
  A driver that only performs actions and never records is VOID by
  construction — the floor is doing its job.
- Durability claims ride `lib/durawatch.py` (manifest + delay-ladder
  re-observation), not immediate asserts.
- Events belong to the *scenario* (armed by the spine via `EVENTS`), not
  hardcoded into drivers. A driver must survive an event landing between any
  two of its steps — that is the point.
- In-process seams (a TS/JS SDK surface, an engine hook) get a thin JS driver
  file invoked by the Python driver; declared in the model as `js:<path>`
  (G2 checks the file exists). The Python spine still owns seeds, clocks,
  ledger, and INVARIANT lines.
- Keep `modules:` current (G8): a new driver that touches a previously
  orphaned module updates its `covered-by:` in the same commit.
