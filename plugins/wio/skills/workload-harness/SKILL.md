---
name: workload-harness
description: Autonomous workload-harness loop for a connected repo. One session alternates producer and executor episodes under a mechanical dispatcher, turning product promises into adversarial workloads, running them via wio, and publishing official results to the status page through the exploration envelope. Invoke via /goal against a connected project; init mode scaffolds .workers/.
metadata:
  author: workers.io
  version: "0.1.1"
---

# Workload Harness

One skill, one session, one loop: scaffold `.workers/` (init), then alternate
**producer** episodes (map areas, draft promises + named explorations) and
**executor** episodes (build a workload, attack one named exploration, record
the verdict) until a stop condition. Publication to the status page rides
official runs — `wio simulate create --exploration <key>` — never separate
upsert verbs.

Invocation:

- `/goal run the workload harness` — full loop; runs until **coverage
  exhausted** (dispatcher row 1). Optional `for N loops` / `until N
  workloads` override the default safety rails (recorded in
  `loop-state.md`) — rails, not targets: the loop should end by exhaustion,
  never by cap.
- `/goal init the workload harness` — deterministic scaffold only:
  [references/init.md](references/init.md).

## Two principles that decide everything

1. **Determinism split.** Deterministic verbs are `wio` CLI calls (create a
   run, fetch status/artifacts). Non-deterministic judgment (what area next,
   which promise matters, is this a real bug, is coverage honest) lives here.
   Never freeze judgment into a verb.
2. **Spec/state split.** Intent — map, areas, promises, named explorations —
   is prose + frontmatter in git under `.workers/`
   ([references/spec-format.md](references/spec-format.md), the frozen
   contract). Run facts live in convex, written only as a side effect of
   running explorations. They join by frontmatter `key`s carried in the
   publication envelope; there is no other coordination channel. Breadth is
   state too: the ranked candidate pool lives in `.workers/backlog.md`
   (spec-format §Backlog) — a file the loop maintains, not an agent and not
   a virtue the prompt requests.

## Hierarchy (pin the vocabulary)

```
Map → Area → Promise (the claim; the page row) → named Exploration (a keyed,
recurring attack: one simulate-create batch per run, grouped over time by its
key) → Runs.
```

One term, one thing: **everything that runs is an exploration.** A *named*
exploration carries a durable frontmatter `key` and publishes to the page; an
*unnamed* one is a draft and shows nowhere. A promise is a growing set of
named explorations — that set is its regression suite. Every promise has at
least `baseline`. **Named or nothing:** there is no anonymous publication.

## The dispatcher (run this checklist at the top of every cycle)

Read `.workers/loop-state.md`, then take the **first** matching row. This is
mechanical — do not reorder, do not blend modes inside one episode.

| # | Condition | Action |
|---|-----------|--------|
| 1 | Stop condition met — **primary: coverage exhausted** (no in-flight or ready work, no pending re-entry or trigger, and the backlog's top active score is below its header threshold); **safety rails:** loop/workload caps hit (defaults 100 loops / 250 workloads). A no-new-information streak is **never** a stop — it is the staleness trigger, row 4. **Aim discipline:** a session may not end by choice while any above-threshold backlog row is un-attacked and rails remain — a ranked seam the loop *named* and never fired at is the most expensive failure mode there is (post-mortems found runs that recorded a real bug's exact seam, rank-1 with file:line, then self-stopped with most of the budget unspent). An above-threshold row is producible work by definition; either attack it, or demote it with a recorded reason, before row 1 can fire. | **Wrap up:** run `.workers/publish.py` (publishes every `status: done` exploration, rewrites `published:` ids), commit specs + evidence + bookkeeping, write the session summary into `loop-state.md`, report — **naming which stop fired**. "Coverage exhausted" is the goal state; a rail hit means coverage remains and the summary must say exactly what was left queued, starting with any above-threshold backlog rows and their scores. |
| 2 | `loop-state.md` names an in-flight unit | **Resume executor** on it — finish or block it before anything else. |
| 3 | `loop-state.md` shows `re-entry: pending <exploration-key>` (set by the executor at every verdict) | **Producer re-entry** — inline, one decision, not an episode: replace the pending line with `re-entry: <exploration-key> → deepen\|switch\|stop — <one-line why>`, then **fold the verdict into backlog L** — reds/near-misses bump the corridor and its same-path siblings, repeated all-greens decay it ([references/producer.md](references/producer.md) §Verdict re-entry + §Score feedback). |
| 4 | A re-plan trigger is set (**new target commits** — `target-head-sha ≠ last-scanned-sha` in `loop-state.md`; executor bounce-backs pending triage; critic-found coverage gap; **staleness** — the no-new-information streak reached K, default 5, tracked in `loop-state.md`) | **Producer episode** — triage first, then extend. **Diff-directed** (new commits): scan `git diff --name-only <last-scanned-sha>..<target-head-sha>`, map changed files to `[path:]` corridors, and run a **diff-directed episode** — re-rank the changed corridors up and **attach sweep budget** to them (dispatch/plan a depth-carrying sweep), leaving untouched-area corridors out even if they top the standing pool; then advance `last-scanned-sha` ([references/producer.md](references/producer.md) §Diff-directed episodes). **Staleness**: refresh the scout fan-out and take the critic's ranking audit before promoting, then reset the streak; the ranking audit folds **user exposure** into backlog L (issue-history-weighted prior, [references/producer.md](references/producer.md) §User-exposure) alongside any pending sweep feedback. Clear the trigger. |
| 5 | Ready entries exist (`status: ready` anywhere in `promises/`) | **Executor episode** on the next ready one (oldest promise first, `baseline` before deeper attacks). |
| 6 | Otherwise | **Producer episode** — promote from the top of `.workers/backlog.md` (recording skips), emit the next batch of named explorations (5–10 across one or more promises), gated by strategy-critic (set + ranking questions). If the backlog is thin (fewer than ~10 active entries above threshold), refresh the scout fan-out first ([references/producer.md](references/producer.md) §Cartographer). |

Coverage exhaustion respects the **ladder floor**: a promise is not covered
below three rungs (baseline + adversarial + fault-boundary) unless
strategy-critic certified its surface smaller — an under-floor promise's
missing rungs are producible work by definition, so row 1 cannot fire over
them.

After every episode: update `loop-state.md` (counters, in-flight, triggers,
re-entry and no-new-information state), then re-run the checklist. If the
session was compacted, this file plus the spec tree *is* the loop — context
is a cache; re-read this skill and resume at row 1.

Episode contracts:
- Producer: [references/producer.md](references/producer.md)
- Executor: [references/executor.md](references/executor.md)
- Critic gates: [references/critics.md](references/critics.md)
- Exploratory sweeps (later mode, not v1): [references/breaker-mode.md](references/breaker-mode.md)

## Workload library and the universal oracle plane

The skill ships a product-agnostic workload library ([lib/](lib/README.md)) and
dependency-service recipes ([references/recipes/](references/recipes/README.md));
init copies both into the repo as `.workers/lib/` and `.workers/recipes/` so
workloads import locally and runs stay hermetic.

Every workload carries the **universal oracle plane** on top of its bespoke
oracles — these catch the symptom classes bespoke oracles are systematically
blind to (graded post-mortems: everything counter-shaped was detectable while
hangs, stranded states, and delayed erasure were invisible):

- **Liveness watchdog** — a global deadline that converts a hang into
  `INVARIANT liveness_watchdog FAIL`. A hang is a red, not a timeout artifact.
- **Terminal-state sweep** — every accepted/acked work item must reach a
  terminal state before exit; a stranded item is a FAIL, not a skipped assert.
- **Acked-durability watch** (`lib/durawatch.py`) — whenever the product acks
  durable effects, manifest them and re-observe on a delay ladder; immediate
  asserts miss delayed erasure.
- **Declared fault timing** (`lib/crashclock.py`) — kills/restarts/held locks
  arm at seed-swept points in a declared timing space, never at magic sleeps.
- **Async parity** — when the API under attack has sync and async forms, the
  workload drives both (or the entry records why not); concurrency defects are
  frequently async-only and sync-only drivers walk straight past them.

Details and the per-step contract: [references/executor.md](references/executor.md).

## Publication model (drafts vs official)

- **Draft:** `wio simulate create` with no identity flag — an unnamed
  exploration. Iterating on shape, chasing a suspected red, tuning the
  oracle — invisible on the status page by construction (verified live, not
  just designed). Iterate freely; reds here cost nothing.
- **Official:** same verb + `--exploration <key>`, but never typed by hand —
  officials are published by `.workers/publish.py`, which walks
  `promises/*.md` and for every `status: done` exploration runs the create
  with `key`, `command`, and `depth` read from the same frontmatter entry.
  Identity and evidence are paired by the spec file; nothing enforces the
  pairing on the wire, so the script is the enforcement. The CLI resolves
  the key in `.workers/` frontmatter, walks up to promise and area, and
  sends the publication envelope on `explorations.create`:
  `envelope: {area: {key, title, description}, promise: {key, title, claim},
  exploration: {key, title, description}}`. The server upserts area and
  promise by **explicit key** — keys are identity, titles/claims/descriptions
  are display and follow the latest publish. Exploration `title` is required
  to publish; `key != slug(title)` is a stderr warning, not an error. Runs
  are stamped with the exploration's display and grouped by its key on the
  promise page. For a finding, the official run replays the recorded seed —
  publication is replay-confirmation.
- **Official runs execute the prepared image at pushed HEAD.** The image is
  pinned to an exact commit: after any push, `wio projects prepare` and poll
  until `preparation.currentImage.commitSha` matches, or creates fail with
  `project_image_missing`. Draft-by-value (`--workload-file`, no commit) is
  the intended fast path, but until worker-side delivery ships the injected
  file does not reach the guest on prod — drafts fall back to
  commit → prepare → run.
- **Auth is the saved wio login.** The CLI bearer covers everything
  headlessly — runs, `projects prepare`, and raw convex HTTP
  (`/api/query`, `/api/mutation`) including `projects:createFromGithub` to
  connect a repo without touching the web app. `WIO_API_KEY` (`fml_…`,
  agent auth) is only needed when no user login exists on the machine.
- **Fallback if publication is unavailable:** record `published: pending`
  and let wrap-up re-fire the official run — the server upsert is
  idempotent, so re-firing is always safe.

## The one rule that keeps the loop honest

**Reward red, not green.** An executor's job is to *falsify* the promise. A
green run is weak evidence; a red run is the win. The two critic gates
(strategy-critic before building, test-reviewer after running) exist to stop
the drift toward useless passing tests. A finding requires replayable
invariant evidence; setup failures are not product bugs; never weaken an
oracle to make a workload pass.

## Operating discipline

- One unit in flight at a time. The loop is serial by design — no claims, no
  leases, no coordination tables.
- Producer owns intent (spec prose, fault models, oracles, exploration sets);
  executor owns workload code, run evidence, and mechanical entry fields.
  Executors never rewrite intent — a deficient spec bounces back with a
  `reason`.
- Weight depth by bug-likelihood: concurrency, state machines,
  retries/idempotency, partial failure, ordering, boundaries. Not even
  coverage.
- Never push to a customer's repo. Specs and workloads live in our fork /
  overlay / the user's own checkout; the only customer-repo write, ever, is
  the graduation PR at the end — and only when asked.

### Long-run operating notes

The loop is built to run for hours and stop on exhaustion, not on a cap.
Three mechanics keep long runs healthy:

- **All subagents run foreground** — scouts and critics alike. Never
  dispatch background subagents: the dispatcher is serial and waits on the
  results anyway, and backgrounded subagents stalled the S2 loop.
- **Batch spec commits.** Official runs execute the prepared image at pushed
  HEAD, and each commit → `wio projects prepare` cycle costs ~60s+. Commit
  an episode's specs and workloads together and share one prepare cycle
  across the batch — never prepare per entry.
- **Prefer multi-seed sweeps per exploration.** Schedule diversity comes
  from depth (more seeds/cases inside one `simulate create`), which is
  nearly free, not from more single-seed runs, which each pay full run
  overhead.
- **Budget follows the census, not a hunch.** The default split of sweep
  compute across strategy classes follows the target's confirmed-bug
  distribution, read as DATA from `.workers/census.md` (a strategy-mix +
  red-rate table), and is reweighted by observed red-rate
  ([references/producer.md](references/producer.md) §Budget allocation). A
  different target's census produces a different split from the same skill —
  the mix is never a constant in this skill.
- **Depth is a superset, not a dice roll.** Seeds are sequential `1..depth`
  per batch — the same depth replays the *identical* seed set every time,
  and a higher depth is a strict superset of a lower one. So re-running an
  exploration at the same depth adds **no** coverage and **no** evidence; a
  repeated all-green there is the same run, not a stronger result. More
  coverage means a *higher depth* or a *changed harness* (different op mix,
  fault set, or timing space) — never a bare re-run. There is no schedule
  control beyond the seed (no PCT, no mutate-near-seed); widen the
  interleaving search at the workload level (barriers + seeded
  permutations), not by asking for more runs of the same batch.
