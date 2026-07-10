# Critics & Falsification

Two failure modes have a green bias: a producer maps what is easy, an executor
writes a workload that passes. Coverage rises, bugs found stays zero. Three
mechanisms fix this.

## 1. Reward red, not green (the mindset)

An executor's job is to **falsify** the promise, not test it. A green run is weak
evidence — the code may be correct, or the workload may be too weak to detect the
violation. The only proof a workload is real is that it **fails on a known
violation**: never trust a green you haven't seen go red. Score on distinct reds
found, not on green workloads written.

## 2. Two distinct adversaries — do not merge them

### `strategy-critic` — is *this* strategy real? (pre-implementation gate)

One critic, asked at **three moments**:

- **Producer, at promotion (the *ranking* question):** audit
  `.workers/backlog.md` before the batch is drafted — what is **overscored**
  (challenge the recorded `L·I·O·N·R/C` factors against the source, cite
  file:line), what **seam is missing** from the pool entirely, and what would
  you **promote instead** of the producer's pick? This is a fresh-context
  challenge against producer anchoring (S2's write-path fixation: five
  write-side promises before the first read-side one). The critic reads the
  backlog header + top ~10 and the map; it may propose new candidates and
  score corrections — the producer inserts/applies or overrules them.
  **The audit also challenges score-feedback and user-exposure moves**
  (producer.md §Score feedback, §User-exposure): an L that changed with no
  `feedback:`/`exposure:` trail is a hand-edit; a corridor green across ≥3
  supersets that never decayed is a stale prior; a `sibling-inherit` across a
  `[path:]` tag that does not actually match the red corridor's path is a
  mis-fire; an `exposure:` bump whose cited confirmed-bug/churn counts do not
  match the issue-history evidence, or applied to a cold path (zero confirmed
  user bugs), is an over-bump; a **budget-plan** whose per-class split does not
  match `census.md` (mix share, or the red-rate reweight) is a mis-allocation
  — all are ranking findings. The audit is also
  where the exposure fold is *applied* if a staleness episode routed here: read
  the issue-history evidence, fold exposure into L per §User-exposure, then
  challenge the result.
  **The producer makes the final promotion decision**; an overrule is
  recorded in the episode summary. This is a challenge to judgment, not a
  transfer of it: no strategist subagent exists — intent-authoring stays in
  the main session.
- **Producer, while planning the ladder (the *set* question):** does the exploration set cover
  the real ways the guarantee breaks? "You have a concurrency attack but no
  retry-after-timeout, no partial-failure-mid-write, no duplicate-replay one." This prevents
  the one-workload trap. The number of named explorations under a promise = the number of distinct fault
  models this critic can name — bounded by the real failure surface, not one and not infinity.
  The set question is also where the critic may **certify a promise's surface
  smaller than the three-rung ladder floor** (baseline + adversarial +
  fault-boundary — see producer.md); that certification, recorded in the
  promise prose, is the only alternative to the floor.
- **Executor, right before writing (the *candidate* question):** is *this* entry a distinct
  fault model with a real oracle, not a wrapper/seed-sweep of an existing one?

Either way it rejects wrappers/seed-sweeps and demands a new oracle/adversarial model, and
weights by bug-likelihood, not even coverage.

**Gate at `ready`, so the executor rarely bounces.** The producer runs strategy-critic
*before* marking an entry `ready` — a `ready` entry is a critic-validated contract. The
executor's pre-write check is then a light confirmation, not a re-litigation; a spec-level
rejection at executor time is a rare escape, not the norm.

### `test-reviewer` — quality of the *single* workload (executor-side gate)

After a workload is written: KEEP / REDO / REMOVE. "Does this genuinely attack
the promise, or is it happy-path / status-200 / coverage-only?" It is about one
workload being real, not about how many. A workload that cannot fail on a planted
violation of its promise is REDO regardless of how clean it looks.

These are **gates, not loops**. Run or emulate `strategy-critic` before an entry is
projected `ready`; run or emulate `test-reviewer` after a workload is written and
run. Neither replaces the producer/executor loop — they admit or reject work.

## How to ask a critic

The critics are **subagents**, not CLI verbs (there is no `wio critic`). Their
briefs ship **inside this skill** and are self-contained —
[briefs/strategy-critic.md](briefs/strategy-critic.md) and
[briefs/test-reviewer.md](briefs/test-reviewer.md):

- **Claude Code:** dispatch a generic read-only subagent (e.g.
  `general-purpose`) whose prompt is the embedded brief plus the entry/diff
  under judgment. It returns `ACCEPT | REDO | BLOCKED` (strategy) or
  `KEEP | REDO | REMOVE` (review) plus the required oracle and the falsification check.
  For the *ranking* question the return is an audit — overscored entries,
  missing seams, counter-promotion — not a verdict; a producer episode that
  promotes can ask the set and ranking questions in one dispatch. Critics
  always run **foreground** (see the long-run notes in SKILL.md). On a normal
  plugin install, `subagent_type: "wio:wio-strategy-critic"` /
  `"wio:wio-test-reviewer"` are acceptable equivalents — but **only** there:
  those agents' definitions read the sibling `wio` skill's reference library,
  so from a standalone copy of this skill that dispatch reads outside the
  copy — use the embedded briefs instead.
- **Codex:** the `.codex/agents/` custom-agent equivalent, same rule.
- **"use or emulate"** = dispatch the embedded brief on a subagent if your host
  supports it, otherwise run its checklist inline yourself. **The main agent
  applies the final decision.**

## What a rejection costs — routing, not a stall

- **Implementation-level REDO** (the workload is weak but the spec is fine): the executor
  redoes it **itself**, in a tight local loop — no producer, no cross-agent delay.
- **Spec-level REDO/BLOCKED** (the fault model, oracle, or setup is deficient): the executor
  **cannot** rewrite the spec, so it sets `result: blocked` with a precise `reason`, sets the
  re-plan trigger, and **moves straight to the next `ready` entry**. The producer triages the
  blocked entry on its next episode.

The loop never idles on a bounce. With the producer gating at `ready` and batching **ahead**
(each producer episode leaves a buffer of `ready` entries), spec-level bounces are rare and cost
per-unit latency, not throughput. The decoupling is the point of the producer/executor split —
don't blend the modes to avoid the round-trip; gate harder and keep the buffer full.

## 3. Weight depth by bug-likelihood

Coverage is not uniform. Point the depth budget where bugs hide: concurrency,
state machines, retries/idempotency, partial failures, ordering, boundaries —
exactly where the fault-injection + deterministic-replay runtime is strongest.

## The proof obligation (the ruler)

A promise's workload is only trusted once it has been seen to go **red on a known
violation and green on the fix**. The planted-bug fixture exists for exactly this:
plant a violation, watch the workload go red, fix it, watch it go green. Until a
workload has demonstrated that sensitivity, treat its green as unproven.
