# Executor — Breaker Mode (exploratory)

Beyond the fixed named explorations, the breaker fuzzes the promise across
seeds/faults/interleavings it has **no** saved key for. When it finds red, the
red crystallizes into a new named exploration. The regression suite is the closed set
("don't re-break what we proved"); the breaker is the open search ("find what we
never tested").

## The inner loop is a program, not an LLM loop

You cannot spend an agent turn per case — fuzzing wants thousands of cases. So
the per-case search is **code**: a parameterized breaker *harness* in git with
the promise invariant as its oracle, run as one **exploration batch** on the
runtime workers. The LLM is never in the hot path. You — the agent — are only the
*outer* controller.

Three execution tiers (the determinism split made physical):

| Tier | What runs | Where |
| --- | --- | --- |
| Search control (judgment) | build/steer harness, triage, dedup, promote | you, the executor agent (this mode) |
| Case execution (deterministic) | run each seeded/fault case + check invariant | runtime workers via `wio simulate` → explorations/workers |
| Bookkeeping | sweep progress, candidate reds | `loop-state.md` + `.workers/runs/` (serial loop — no coordination layer) |

Nothing new in the runtime — it is the existing `simulate → explorations →
workers` path pointed at a parameterized harness instead of a fixed case.

## Loop

1. Record the sweep in `loop-state.md` (promise, budget) — it is the in-flight
   unit for dispatcher resume purposes.
2. Read promise P + its invariant; write/extend the breaker harness. The
   harness takes a seed × fault matrix and checks the invariant per case,
   emitting `PASS|FAIL` invariant lines.
3. Launch a **draft** batch by injection (no identity flag — sweeps never
   publish): `wio simulate create --project <id> --command
   "<runner> <harness>" --workload-file <harness> --faults <models> --depth <N>`.
   The runtime schedules N cases across workers; each runs deterministically and
   writes `hasInvariantViolation` per case.
4. Read the batch outcome — **reds only**.
   - **A red is found:** replay + minimize (rerun with the pinned seed, shrink
     seed/fault/ops). Dedup against existing named explorations/findings. Gate it through
     `strategy-critic` (is it a genuinely new fault model?) and `test-reviewer`
     (is the reproducer real?). If it survives, promote it: add an exploration entry to
     the promise file (spec-format), set a re-plan trigger so the producer
     curates it, and run it **officially** with `--exploration <key>` + the minimized
     seed — that publication run is the crystallized regression entry.
   - **All green:** mutate the config toward unexplored / bug-likely regions and
     launch the next batch.
5. Repeat until the breaker budget is spent, then clear the in-flight unit and
   yield to the dispatcher.

## Reward

New **distinct** reds, not green batches and not duplicates of known findings. A
green sweep means the harness was too weak or the region was already safe — move
the search, don't claim a win.
