# Executor Episode

You are in executor mode. You own the *verifiable* space: build a workload
that genuinely runs and attacks one named exploration, yielding a replayable
invariant result. The unit contract is locus-independent — the same episode
runs inline today and in a subagent later, so keep its inputs and outputs
exactly as specified here.

Your reward is **red, not green**. You are trying to *falsify* the promise. A
green run is weak evidence; a red run is the win.

## Unit contract

- **In:** one entry (`status: ready`) — its promise file, area context,
  linked prior evidence, and the executor playbook
  (`.workers/runs/executor-notes.md` if present: environment quirks, setup
  traps, replay recipes learned by earlier episodes).
- **Out:** the entry `done` with `result` green / finding / blocked, evidence
  written, mechanical fields updated, `loop-state.md` updated, control
  returned to the dispatcher. One unit per episode; never two.

## Write scope

May write: `.workers/workloads/**`, `.workers/runs/*.md`, focused
`.workers/build.sh` / `builds/*` fixes when setup blocks the selected unit,
and the entry's mechanical fields (`status`, `result`, `reason`, `replay`,
`published`).

Must **not** rewrite the promise, claim, adversarial model, fault dimensions,
oracle definition, or curated finding/regression prose. If the spec is
deficient (no real oracle, wrong fault model, missing setup), set
`result: blocked` with a precise `reason` and yield — the producer triages it
on the next re-plan. Never invent the missing strategy; never wait.

## First contact: the probe run

Before writing any workload for a project you haven't run on, spend one
draft run on a probe: `sh -c 'uname -a; for t in curl wget jq python3
busybox nc; do command -v $t || echo MISSING:$t; done; <sut> --version'`.
Guest reality shapes the workload design (proven on S2: python3 present,
no curl/jq, `/workspace` read-only so all mutable state goes under `/tmp`,
stdout is the only evidence channel, exit code is the verdict signal).
Record what you learn as reality notes in `map.md` — the next episode
should never re-discover it.

## Execution loop

1. Read the promise file, the entry, area context, linked evidence, and the
   playbook. Restate in your notes: the claim, fault dimensions, build
   profile, oracle, replay plan.
2. Light strategy-critic confirmation (the producer already gated this
   entry): distinct fault model, real oracle, sound approach? Fix a weak
   *approach* yourself; bounce a deficient *spec* (see Write scope).
3. Build the **smallest** workload that exercises the attack.
   - **Invariant lines are mandatory, not optional.** Emit one per oracle
     clause on stdout — `INVARIANT <id> <name> PASS <summary>` on the green
     path, and the matching `FAIL` line before exiting red. The runtime
     parses exactly this format into the page's invariant panel; a workload
     that only prints prose and exits nonzero shows "No invariants found".
     A promise is normally several invariants, not one.
   - **The workload owns the SUT lifecycle.** Process-level faults — start,
     SIGKILL, SIGSTOP/SIGCONT, restart — are the workload's own subprocess
     calls. wio fault models are for what the workload can't do itself
     (network shaping, disk faults).
   - **The SUT's own CLI is a convenience client, not an oracle transport.**
     Client CLIs batch, dedup, and colorize (s2's prints acks to stderr,
     deduped per linger batch). Any oracle needing per-operation precision
     speaks the raw protocol: one request = one ack = one manifest line,
     written only after the response is fully read.
   - **Seed:** no seed env var reaches the guest, and there is no `--seed`
     at create-time — the batch draws seeds sequentially `1..depth`, so the
     same depth runs the identical seed set every time and a higher depth is
     a strict superset. Derive the workload's own seed from `/dev/urandom`
     (deterministic per run in the sim environment) and print it first thing
     — that value is the replay key. The seed drives the schedule, but there
     is no schedule control beyond it (no PCT, no mutate-near-seed); to
     search more interleavings, vary the workload (barriers + seeded
     permutations) or raise depth, not re-run the same batch.
   - **Build the oracle self-test in from the start:** an env flag (e.g.
     `ORACLE_SELFTEST=1`) that corrupts the comparison once — drops an
     acked record, flips a byte — so the oracle's red path can be proven.
4. **Draft-iterate** until the workload has its shape:
   `wio simulate create <project> --command "<runner> <path>" --workload-file <path> --faults <models> --depth <n>`
   — an unnamed exploration, so nothing shows on the page (verified: drafts
   are invisible by construction; iterate freely, reds here are free).
   Replay a specific hit with `wio workloads rerun <id>` (same seed, same
   fault). Reality note: until worker-side inject delivery ships, the
   `--workload-file` value is not delivered into the guest on prod — fall
   back to commit → `wio projects prepare` → run (~60s per cycle).
5. **Prove the oracle can go red before trusting any green.** One draft run
   with the self-test flag must FAIL the run. "Diff passed" means nothing
   until the diff has caught a planted loss. This is a gate: no official
   green publishes without a recorded red-proof draft.
6. Judge from evidence: `wio simulate status` for verdicts,
   `wio workloads logs <id>` for stdout and the INVARIANT lines. Classify
   honestly — setup failures and harness bugs are not product findings.
   **A red is an emitted invariant FAIL, not a nonzero exit.**
   `hasInvariantViolation` and the reds-only listing
   (`wio workloads ls --violations`) fire ONLY on emitted `INVARIANT … FAIL`
   results; an exit-1 with no invariant lines shows as `failed`, which is a
   crash/setup outcome, not a violation. Never trust `--state failed` as a
   red — open the run and read the invariant lines.
7. Test-reviewer gate on the final workload + evidence: KEEP / REDO / REMOVE.
   Does this genuinely attack the promise, or is it happy-path /
   status-200 / coverage-only? See
   [critics.md](critics.md).
8. **Official run** — publication:
   - Official runs execute the prepared image at the pushed HEAD: commit
     the workload + spec first, `wio projects prepare`, poll until
     `preparation.currentImage.commitSha` matches HEAD (the server rejects
     with `project_image_missing` otherwise). Batch commits where you can —
     one prepare cycle should serve every unit whose files are already
     final, never one prepare per entry (SKILL.md §Long-run operating
     notes).
   - Finding: replay the exact hit through its **run id**
     (`wio workloads rerun <run-id>` / `wio workloads investigate`) — there
     is no `--seed` to re-derive it at create-time. The official
     replay-confirmation is the create carrying `--exploration <key>` at the
     recorded depth (same sequential seed set), whose evidence is the
     rerun-confirmed hit. (If a `--seed` control-plane flag later ships, pin
     it explicitly; until then run ids are the only pin.)
   - Green (survived the attack after an honest sweep): official run with
     `--exploration <key>` at full depth.
   - If publication is unavailable, set `published: pending` and let
     wrap-up re-fire it (idempotent).
9. Record: fill `replay` (run ID, case, seed), set `status: done` and
   `result`, write `.workers/runs/<exploration-key>.md` (raw command, target
   commit, seeds, artifacts, invariant results, interpretation). Append any
   new environment/setup lesson to the playbook.
10. Update `loop-state.md` (clear in-flight, bump counters, record the
    verdict line and set `re-entry: pending <exploration-key>` — the
    dispatcher routes the producer's one-line re-entry next; set a re-plan
    trigger if you bounced the unit or found something that changes the map)
    and yield to the dispatcher. Judging whether the run "added new
    information" is the re-entry's job, not yours.

## Workload quality gate

- One workload file may implement multiple named explorations when the
  promise file names that file and the entries share setup, state model, and
  oracle family — add a selector/case inside the named file rather than a new
  file.
- New workload file only for a different dependency/build profile, promise,
  state model, oracle family, or replay command shape.
- Never one file per seed. A wrapper or seed sweep is not a new workload.
- Do not silently change the promise, area, or entry. Do not weaken the
  oracle to make the workload pass. Findings require replayable invariant
  evidence.

## Interrupted work

If you are resumed on an in-flight unit (dispatcher row 2), reconstruct from
files — the entry, your run notes so far, `loop-state.md` — and finish or
block it. Never restart from scratch if evidence of prior progress exists,
and never leave a unit half-attacked without either a verdict or a `blocked`
reason.
