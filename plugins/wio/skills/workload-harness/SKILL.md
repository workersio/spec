---
name: workload-harness
description: Autonomous usage-first workload-harness loop for a connected repo. One session alternates producer episodes (maintain the usage model, emit scenario batches) and executor episodes (run one scenario, red-proof its oracles, record the verdict) under a mechanical dispatcher, running scenarios via wio. Greenfield v2 — scenarios only; no promises, areas, or backlog. Invoke via /goal against a connected project; init mode scaffolds .workers/.
metadata:
  author: workers.io
  version: "0.1.6"
---

# Workload Harness (usage-first)

One skill, one session, one loop: scaffold `.workers/` (init), then alternate
**producer** episodes (build and maintain the *usage model*, rank candidates,
emit batches of named scenarios) and **executor** episodes (run one scenario,
red-proof its oracles, record the verdict) until a stop condition. The unit of
work is the **scenario** — a cast of personas exercising flows while a
real-world event lands. Nothing else runs; nothing publishes (this lane is
draft-only by design).

Invocation:

- `/goal run the workload harness` — full loop; runs until **model
  exhausted** (dispatcher row 1). Optional `for N loops` / `until N scenarios`
  override the safety rails recorded in `journal.md` — rails, not targets.
- `/goal init the workload harness` — deterministic scaffold only:
  [references/init.md](references/init.md).

## Two principles that decide everything

1. **Determinism split.** Deterministic verbs are `wio` CLI calls and
   `.workers/check.py`. Non-deterministic judgment (what the product is *for*,
   which situation matters next, is this red a real bug) lives here. Never
   freeze judgment into a verb.
2. **Usage first — with rare usage enforced, not advised.** Generation starts
   from how the product is *used* — personas × flows × real-world events — not
   from code seams. Rare bugs come from **importance sampling**: a realistic
   operation carrier with rare events and rare usage deliberately amplified,
   never from uniform randomness and never from corridor enumeration. Traffic
   weighting aims the mass; the **seven stop gates** stop it collapsing onto the
   product's hardened core: every flow covers its documented **modalities**
   (sync/async/threaded) or parks each with a cited, critic-audited reason;
   the **documented-surface census** (finer than modules) must have zero
   orphans; the `api-explorer` rarity persona's **api-floor share is binding**;
   every amplified **event** must actually fire in a done scenario; the
   **`contract-abuser` misuse persona** (invalid spec, wrong-context call,
   double-call, pathological ids, non-serializable args) must have fired,
   riding the error-contract oracle; and the **aim-debt gate** — every mapped
   surface whose flow carries a live oracle, once baselined green, owes an
   *attacking* scenario (L1+) before budget goes to another baseline (an
   un-falsified promise is not coverage). The usage model is the spec; the
   scenario is the test; the story is the user-facing sentence.

## Vocabulary (pin it)

```
Usage model (personas · flows+invariants · events · actor-model · modules)
  → Candidates (ranked situations: cast × flows × event × rung)
    → Scenario (a named, keyed file — THE unit that runs)
      → Runs (wio workloads, seeds 1..depth)
        → Finding (a crystallized, minimized, replayable red)
```

One term, one thing: **everything that runs is a scenario.** A scenario's
`key` is immutable and project-unique; `invariants:` are inherited from its
flows in the model — the claims live there, not in hand-authored promise
files. The **ladder** rungs situate every scenario: L0 solo flow → L1
same-flow contention → L2 flow interaction → L3 + world event → L4 horizon
(long soak). L0 before L1 before L2 for any given flow.

## The dispatcher (run this checklist at the top of every cycle)

Read `journal.md` + `check.py --status`, then take the **first** matching
row. Mechanical — do not reorder, do not blend modes inside one episode.

| # | Condition | Action |
|---|-----------|--------|
| 1 | Stop — **primary: model exhausted AND gates clear** (every model flow at its ladder target or parked with reason; top candidate score below the header threshold; no un-crystallized red; `check.py` clean including G8/G11; **`check.py --status` prints `STOP-BLOCKERS (0)`** — the seven stop gates: modality parity, surface census, api-floor share, event coverage, misuse floor, park audit, aim-debt) — or safety rails hit (defaults 100 loops / 250 runs). A no-new-red streak is never a stop; it is the model-refresh trigger, row 4. An open STOP-BLOCKER is not a stop reason — it is the *work list*: aim the next episodes at exactly the named blockers. | **Wrap up:** commit specs + evidence, append the session summary to `journal.md`, report — naming which stop fired. A rail hit must say exactly what was left: ready scenarios, un-run candidates and their scores, un-crystallized reds, open stop-blockers. |
| 2 | A scenario is in-flight (`status: running` in `journal.md`) | **Resume executor** on it — finish or block it before anything else. |
| 3 | An un-crystallized **RED** exists (`result: finding` with no `findings/` file) | **Crystallize** ([references/executor.md](references/executor.md) §Crystallize): minimize via `scenario_gen.shrink` (drop actors → flows → ops → depth), re-confirm red at the shrunk shape, test-reviewer gate, write `findings/<key>.md` with the replay recipe. Reds never queue behind new work. |
| 4 | Model-refresh trigger: candidates thin (<5 above threshold), staleness (no new red in K=5 episodes), or an executor bounced a scenario on a model gap | **Producer episode** — refresh the usage model: scout fan-out (foreground, read-only) over docs/examples/issues for unmodeled personas, flows, events; re-rank candidates; strategy-critic model audit before promoting. Clear the trigger. |
| 5 | Ready scenarios exist (`status: ready`) | **Executor episode** on the next one (lowest rung first per flow; a flow's L0 before its L1) — [references/executor.md](references/executor.md). |
| 6 | Otherwise | **Producer episode** — emit the next batch of 5–10 named scenarios from the top of `candidates.md`, gated by strategy-critic (model + set audit) — [references/producer.md](references/producer.md). |

After every episode: append to `journal.md` (episode line: counters, verdicts,
triggers), run `check.py` (must exit 0 before the episode counts), then re-run
the checklist. If the session was compacted, `journal.md` + the tree + this
skill **is** the loop — context is a cache; resume at row 1.

Episode contracts:
- Producer (model, candidates, batches): [references/producer.md](references/producer.md)
- Executor (run one scenario) + Crystallize: [references/executor.md](references/executor.md)
- Critic gates: [references/critics.md](references/critics.md)
- Format (frozen contract): [references/scenario-format.md](references/scenario-format.md)

## The library and the oracle plane

Init copies [lib/](lib/README.md) into the repo as `.workers/lib/` and
dependency recipes into `.workers/recipes/` — workloads import locally, runs
stay hermetic, behavior is version-pinned with the corpus. The one runnable:

```
<runner-prefix> .workers/lib/run_scenario.py .workers/scenarios/<key>.md
```

(`runner:` prefix from `usage-model.md`, e.g. a postgres wrapper + venv
python; `lib/CONTRACT.md` is the exact runtime contract.) Every scenario
carries the **universal oracle plane**:

- **Persona ledger** (`lib/personaledger.py`) — per-actor: everything this
  actor was told succeeded is still true for it; nothing it was denied
  happened anyway. This is what keeps a composite scenario sharply
  falsifiable — oracle strength *scales with* cast size instead of diluting.
- **Error contract** (`lib/errorcontract.py`) — every failure is the
  *promised* failure: documented errors where documented, never an internal
  exception, a wedge, or a silent success.
- **Wall-clock bounds** (`lib/wallclock.py`) — declared per-step latency
  bounds; bounded-extra-delay violations are reds.
- **Liveness watchdog** — a hang is `INVARIANT liveness_watchdog liveness
  FAIL`, never a timeout artifact.
- **Acked-durability watch** (`lib/durawatch.py`) — acked durable effects are
  manifested and re-observed on a delay ladder; immediate asserts miss
  delayed erasure.
- **Declared event timing** (`lib/crashclock.py`) — crashes/restarts/held
  locks arm at seed-swept points in a declared timing space, never at magic
  sleeps.
- **Terminal-state sweep** — flow modules may export `sweep(sut)`; every
  accepted work item must reach a terminal state before exit.

## Red-proof, VOID, and seeds (the epistemics kit — non-negotiable)

- **No green is trusted until the oracle has been seen red.** Every scenario's
  first gate is a `--redproof` draft run: `run_scenario` plants a violation in
  the *observation channel only* (never the SUT), and the run must catch it
  (`ORACLE_SELFTEST PASS`, exit 0). The run id goes in `redproof:`;
  `check.py` **G5** fails the compile on any `done`+`green` without it.
- **VOID floors.** An oracle that witnessed nothing reports VOID (exit 3),
  never green. A VOID is bookkept, investigated, and does not count as
  coverage.
- **Deterministic seeds.** Seeds are sequential `1..depth` per batch — the
  same depth replays the identical seed set; a higher depth is a strict
  superset; a bare re-run adds nothing. Replay pins by run id
  (`wio workloads rerun <id>`) or `--seed`. `SEED` and `PLAN` lines make
  every case reconstructible from stdout alone.
- **Setup failures are not findings** (`setup-block:`, exit 44) and a red is
  an emitted `INVARIANT ... FAIL` line — never a bare nonzero exit.

## The one rule that keeps the loop honest

**Reward red, not green.** An executor's job is to falsify the flow
invariants under realistic-plus-amplified usage. A green run is weak
evidence; a red run is the win. Never weaken an oracle to make a scenario
pass. The two critic gates (strategy-critic before building, test-reviewer
after running) exist to stop the drift toward useless passing tests.

## Operating discipline

- One scenario in flight at a time. The loop is serial by design.
- Producer owns the usage model, candidates, and scenario frontmatter intent;
  executor owns flow-driver code, run evidence, and the mechanical result
  fields. Executors never rewrite the model — a model gap bounces the
  scenario back with a `reason` (row 4 trigger).
- `check.py` is the format: any format change lands in the same commit as the
  `check.py` change that enforces it, or the change didn't happen.
- Every scenario has a `story:` a non-engineer can read — legibility is a
  frontmatter field, not an afterthought.
- Never push to a customer's repo. Findings accumulate locally in
  `findings/` pending triage; issue filing stays with the human (≤2 open per
  repo; the report skill gates every send).
- All subagents run foreground, briefed self-contained from
  `references/briefs/` on generic read-only subagents.
- Batch spec commits: official-image runs execute pushed HEAD and each
  commit → `wio projects prepare` cycle costs ~60s+; share one prepare per
  episode batch. Prefer depth (multi-seed sweeps) over more single-seed runs.
