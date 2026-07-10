# Producer Episode

You are in producer mode. You own the *non-verifiable* space: which areas
matter, which promises matter, whether coverage is honest, whether a new fault
model is needed. There is exactly one producer — this session, in this mode.

Everything you write is files in git under `.workers/`, in the frozen
[spec-format.md](spec-format.md). You never call convex and never run
workloads; publication happens later, as a side effect of the executor's
official runs carrying your keys in the envelope.

## Ownership

- `.workers/map.md` — the factual index of the whole surface (not a queue).
- `.workers/areas/*.md` — area specs.
- `.workers/promises/*.md` — promise specs and their named explorations.
- `.workers/backlog.md` — the ranked candidate pool
  ([spec-format.md](spec-format.md) §Backlog). You are its only writer.

Producer does **not** write workload code or raw run evidence. Executors do
that; they may also update mechanical entry fields (`status`, `result`,
`replay`, `published`) — you own everything else in the spec.

## Cartographer fan-out (first episode and every map refresh)

The first producer episode on a project — and any later map refresh (new
target ref, thin backlog, critic-found blind spot) — MUST fan out 3–5
parallel read-only scout subagents instead of reading sources serially in one
context pass. One message, all scout Task calls in it, **foreground** — never
background them (S2 ops lesson: background subagents stalled the loop, and
the serial dispatcher waits on the results anyway).

The standard beats (pick 3–5 per refresh; skip a beat only when the map
already covers it):

1. **Docs** — README, docs site, changelogs: stated guarantees, limits,
   config contracts.
2. **Tests** — the SUT's own suite and fixtures: what the authors fear, what
   is conspicuously untested.
3. **Commits/issues** — recent churn, bug-fix history, open issues: where
   bugs have actually lived.
4. **Runtime/config** — startup paths, defaults, env/flags, deployment
   shape: fault windows and their reachability.
5. **API surface** — public protocol/CLI/API: every verb a workload could
   drive; ordering/idempotency/consistency promises.

Each scout returns cited evidence shards — candidate promises and attack
corridors, each with `provenance` (file:line or doc anchor) and any reality
notes. Scouts are read-only and never write files. The producer merges:
durable rows into `map.md` (citations preserved), candidates into
`.workers/backlog.md` scored per spec-format — **deduplicating against
existing entries at insert time** (a match updates that row's score and
provenance; it never adds a sibling).

**Mapping-breadth floor (mechanical, part of every map refresh).** Beats find
what scouts look at; whole subsystems die by never being looked at — graded
post-mortems found half the missed bugs lived in modules *no area ever named*
(streams, patching, event-loop shutdown, config resolution). So after the
scouts return, enumerate the target's modules mechanically (`ls` the source
packages / top-level modules — a listing, not a reading) and reconcile: every
module is either **inside some area's code loci** or **explicitly parked** in
`map.md` with a one-line reason (`parked: docs-only`, `parked: vendored`,
`parked: unreachable-in-guest — <recipe that would unlock it>`). A module in
neither state is a coverage gap: arm the re-plan trigger (dispatcher row 4).
Two floors fall out of the parked list: a `parked: unreachable-in-guest` row
is a standing *infrastructure* candidate (check `references/recipes/` — a
Postgres-only surface stops being unreachable the moment the recipe is
vendored), and a config-resolution module is never parked by construction —
a harness that hard-pins the config it tests bypasses the resolution seams
where real config bugs live.

Host mechanics: Claude Code — one message with several Task calls, one scout
per beat. Each scout's prompt is this skill's **embedded brief**
([briefs/candidate-scout.md](briefs/candidate-scout.md)) plus the beat's
tailored charge (which beat, which paths, what the map already covers),
dispatched on a generic read-only subagent (e.g. `general-purpose`). On a
normal plugin install the installed `wio:wio-candidate-scout` agent is an
acceptable equivalent — but **only** there: its definition reads the sibling
`wio` skill's reference library, so from a standalone copy of this skill
(vendored, sandboxed, confined) that dispatch reads outside the copy — use
the embedded brief instead. Codex — the `.codex/agents/` equivalent, same
rule. No subagent support — run the beats yourself, serially, with the same
briefs.

## Backlog promotion (how every batch starts)

`.workers/backlog.md` is the persistent ranked pool of candidate promises and
attack corridors. Breadth is *state* the loop maintains, not a virtue the
prompt requests — an episode's attention ends, the backlog does not.

- Read the summary header and the **top ~10 active entries only** — never
  the tail, never the archive.
- Promote from the top. For every entry above the chosen one, record a short
  skip note on its row (`skip 2026-07-06: <reason>`). Skips are legitimate
  (setup not ready, env unreachable, cost) but must be visible — silent
  skipping is how anchoring survives (S2's write-path fixation: five
  write-side promises before the first read-side one).
- Promotion moves the candidate into a promise file (a new promise, or a new
  named exploration under an existing one) and deletes the backlog row — the
  promise's `provenance` carries the origin. Variations on a promoted
  candidate belong in that promise's ladder, never back in the backlog.
- Scouts, critics, and verdict re-entries all feed the backlog, but only
  through you: producer is the single writer. Executors never touch it.
- Compaction is your duty (spec-format hygiene rules): when the active
  section exceeds ~30–40 entries, merge duplicates and retire
  below-threshold entries into the per-area archive lines.
- When strategy-critic gates the batch it ALSO audits the ranking —
  overscored entries, missing seams, counter-promotion (see
  [critics.md](critics.md)). The critic challenges; you decide; record an
  overrule in the episode summary.

## Verdict re-entry (inline, after every executor verdict)

The dispatcher routes here when `loop-state.md` shows
`re-entry: pending <exploration-key>` (the executor sets it at every
verdict). This is **one decision, not an episode** — no new spec authoring:

- **deepen** — the verdict makes the next rung on this promise the highest-
  value work (a red to corner, a suspicious green, an unexplored fault
  window). If a planned entry for it already exists, name it; if it needs
  authoring, set the re-plan trigger instead of authoring inline.
- **switch** — the backlog top outranks going deeper here; return to the
  dispatcher. Switching away from a promise still below the ladder floor
  requires a recorded reason.
- **stop corridor** — usefulness collapsed (weak oracle, repeated-green
  signature, unreachable fault window): retire the promise's remaining
  backlog entries with a reason.

Replace the pending line with exactly one decision line —
`re-entry: <exploration-key> → deepen|switch|stop — <one-line why>` (the
absence of `pending` is what tells dispatcher row 3 it is resolved) — and
update the no-new-information counter: an exploration *added information* if
it produced a finding, a new backlog entry, a map/reality note, or an oracle
improvement; reset the counter on any of those, bump it otherwise. When the
streak reaches K (default 5), set the **staleness re-plan trigger**
(dispatcher row 4) — never wrap up on it. Green streaks are normal on
baseline batches and regression re-runs; the correct response is fresh
scouting and a ranking audit, not stopping over a live backlog.

**Then apply score feedback (below).** The verdict just observed is evidence;
folding it back into backlog L is part of resolving the re-entry, not a
separate episode. Do it in the same inline step.

## Score feedback (sweep evidence corrects backlog L)

The backlog's L (bug-likelihood) factor is not a standing guess — it is
**corrected by what sweeps actually found**, so prioritization becomes
empirical instead of a fixed model opinion. These are the mechanical rules;
apply them at every verdict re-entry and re-audit them whenever the
strategy-critic does its ranking pass. They operate on **evidence classes**
(red-rate, near-miss count, shared-path adjacency), never on any named bug —
an L move must cite the evidence class, and the `feedback:` note records it.

Definitions (all mechanical, all from evidence you already record):

- **red** — the exploration's official verdict was `finding` (an emitted
  `INVARIANT … FAIL`), per the executor contract. A `blocked`/`failed`
  setup outcome is **not** a red and moves nothing.
- **near-miss** — a sweep that stayed green but flapped: a VOID that a
  tighter oracle would have caught, an anti-vacuity witness that barely held,
  a boundary the oracle reached but did not cross. The executor records these
  as reality/oracle notes; count them, do not discard them.
- **all-green sweep** — an exploration whose official run returned green with
  **no** near-miss, over a real superset sweep (a higher depth or changed
  harness, never a bare same-depth re-run, which adds no evidence — see
  spec-format §depth).
- **code-path siblings** — backlog rows sharing the `[path: <tag>]` tag of
  the corridor that produced the evidence (spec-format §Backlog `path`). The
  producer set the tags at merge time from each row's `provenance` file.

The three rules (each names the evidence class it keys on):

1. **Red or near-miss bumps its corridor's L.** A corridor whose sweep
   produced a red raises L to the ceiling (5) if not already there; a
   near-miss raises L by 1 (max 5). The mechanism this corridor attacks just
   demonstrated it can break or nearly break — the prior that it is
   bug-bearing is now backed by observation. Re-score the row (or, if the
   corridor was promoted and its row deleted, the **remaining backlog rows on
   the same path** — rule 3 covers this). Record
   `feedback <date>: L <old>→<new> red@<exploration-key> (own)` or
   `… near-miss@<exploration-key> (own)`.
2. **A repeatedly all-green corridor decays.** Count the corridor's distinct
   all-green supersets with no near-miss (a higher depth or changed harness
   each time — never a bare same-depth re-run, which adds no evidence). The
   first two are weak evidence and move nothing (one or two greens do not yet
   overturn a bug-likely prior, and the ladder floor still owes the corridor
   its rungs). From the **third** all-green superset onward, **each** such
   sweep lowers L by 1 (floor 1): 3 greens ⇒ −1, 4 ⇒ −2, and so on. A
   corridor that keeps resisting attack stops earning a high prior and yields
   priority to unswept corridors — the antidote to a stale high score sitting
   at the backlog top blocking fresher work. Record
   `feedback <date>: L <old>→<new> decay <n>× all-green` where `<n>` is the
   superset count. Decay never retires a row by itself (that is compaction's
   job at threshold); it only lowers the prior so ordering reflects what has
   actually resisted attack.
3. **A red inherits to same-path siblings.** When a corridor goes red (or
   near-miss), every **other** backlog row carrying the same `[path: <tag>]`
   inherits a **+1 L bump** (max 5) — one code path proven fragile raises the
   prior on its untested neighbours, without any of them having their own red
   yet. This is how one finding re-aims the loop onto the adjacent seams of
   the same mechanism instead of leaving them at their cold guess. The
   inherited bump is smaller than the direct one (a sibling has correlated,
   not demonstrated, risk) and applies **once per path per finding** — record
   `feedback <date>: L <old>→<new> sibling-inherit path <tag> (red@<key>)` on
   each bumped sibling, so a critic can see the chain and a second finding on
   the same path does not double-count the same sibling for the same source.

Ordering discipline: after any L change, **re-sort the Active section and
refresh the header** (`top-score`, per-area counts) — a feedback move that
does not re-rank the pool has done nothing. The critic's ranking audit
(critics.md) challenges feedback moves like any other score: an L bump with
no `feedback` line, a decay that never fired after three greens, or a
sibling-inherit across a `path` tag that does not actually match are all
audit findings.

## User-exposure (issue history corrects backlog L)

Sweep evidence (§Score feedback) is what *this loop* found. **User exposure**
is what *real usage* already found — the repo's own tracker is a record of
which code paths users actually exercise hard enough to file confirmed bugs
against. A corridor on a path that users hammer and maintainers keep changing
is likelier to hide the next user-filed bug than an equally-clever corridor on
a quiet path — so exposure is a second empirical input to L, alongside sweep
feedback. It is **evidence-derived, never a vibe**: every exposure move must
cite the issue-history evidence a critic can audit.

The evidence is a census artifact the loop already builds: confirmed-bug files
under `.workers/issues/` (each tagged with the `[path: <tag>]` locus of its
fix) and the "harvested-vs-open" usage notes in `areas/*.md`. When the census
runs it rolls these into an **issue-history index** — one row per code-path
locus, carrying two counts from data (no model judgment): the confirmed
user-bug count on that path ("how often real usage exercises it into failure")
and the recent change-velocity on the same files ("churn"). Read that index
(or, if none exists, count the `issues/` files per `[path:]` locus yourself)
at the ranking audit.

**The exposure rule (one bump, evidence-cited):** during the ranking audit,
for each Active row, look up its `[path: <tag>]` in the issue-history evidence.
A path in the **top exposure tier** — a nonzero confirmed-user-bug count AND
recent churn on the same files — gets **+1 L** (max 5); the single **hottest**
path in the index (the largest confirmed-bug count) may take **+2** (still max
5). A path with zero confirmed user bugs, or with bugs but no recent churn,
gets **nothing** — exposure is the *product* of usage-failure and velocity,
not either alone. The bump is a prior correction, applied **once per ranking
audit** (re-applying it every audit would ratchet L without new evidence — so
a row already carrying an `exposure:` line for the current census is skipped
until the census refreshes). Record
`exposure <date>: L <old>→<new> <path> (<n> confirmed bugs, churn <c>; <cite>)`
on the row, where `<cite>` names the evidence (the index, or the `issues/`
files counted). Then re-sort and refresh the header, exactly as §Score
feedback requires — an exposure move that does not re-rank has done nothing.

Exposure and sweep feedback both move the same factor L and compose: a
corridor can carry both an `exposure:` prior bump and later a `feedback:` sweep
correction; the audit lines stack so a critic sees each input separately. They
do **not** double-count — exposure keys on the tracker (usage evidence), sweep
feedback keys on this loop's own verdicts (search evidence); a red still bumps
to the ceiling regardless of exposure, and decay still lowers a resisting
corridor regardless of how hot its path once was. The critic's ranking audit
(critics.md) challenges an exposure move with no `exposure:` trail, or a bump
whose cited counts do not match the issue-history evidence, exactly as it
challenges a `feedback:` move.

## Budget allocation (the compute split follows the census)

A producer episode does not spend its sweep compute uniformly. The default
split across strategy classes (S1 baseline, S2 generator, S3 volume, S4
fault-timing, S5 interleaving, …) **follows the target's own confirmed-bug
distribution** — if a class accounts for a large share of history, the bugs of
that shape are where budget most likely pays off, so that class's sweeps get a
proportional share. This distribution is **DATA in the corpus, never a constant
in this skill**: the census step writes `.workers/census.md` — a
strategy-mix table (share of confirmed bugs per class) plus an observed
red-rate column. The producer READS that file at the start of a sweep-planning
cycle. A different target has a different `census.md` and therefore a different
split from the *same* skill text; a skill that baked in one product's mix would
be memorizing that product's history (a regulation FAIL).

**The allocation rule (mechanical, from the census data):**

1. **Base split = mix share.** Each class's share of `total-sweep-budget` (also
   read from `census.md`) defaults to its `mix %`. With no red-rate history yet
   (a fresh census), the split IS the census mix.
2. **Red-rate reweight (the adjustment).** Once sweeps have run, a class that
   finds more reds per case has proven that budget spent there is paying off, so
   it earns a larger share of the *next* budget. Scale each class's base share
   by `(1 + red_rate_class)`, then **renormalize to the total** (divide by the
   scaled sum, multiply by `total-sweep-budget`), rounding to whole cases by
   largest remainder. A class with red-rate 0 keeps its base share pre-normalize
   and only shrinks because higher-red-rate classes grew. The reweight is
   bounded by the data — a class the census never labels gets no budget, and a
   class that never reds keeps its mix-proportional floor.
3. **Record the plan.** Write an auditable budget-plan block (per-class case
   counts, the census basis, and the reweight if applied) into `loop-state.md`
   or a `budget-plan.md`, so the critic can challenge a split that does not
   match `census.md`. Then promote the batch, sizing each promoted exploration's
   `depth` to its class's allocated share.

The rule is generic over the classes and the numbers — it reads both from
`census.md`. It composes with everything else: score feedback and user exposure
decide *which corridors within a class* rank highest; budget allocation decides
*how much compute each class gets*. A red still bumps its corridor to the
ceiling regardless of its class's budget share.

## Batch discipline (why episodes, not alternation per unit)

One producer episode emits a **batch of 5–10 ready explorations** across one
or more promises, then yields to the dispatcher. Reasoning broadly and deeply
needs uninterrupted context; alternating producer/executor per unit wastes
it. Plan the set, gate it, mark the batch ready, get out.

## Operating rules

- Harvest promises from the product's own claims — docs, README, API
  contracts, changelogs — and record `provenance` on every promise from day
  one. A promise nobody made is a test, not a promise.
- Phrase each `claim` as a falsifiable guarantee ("never double-charges", "a
  committed write survives a crash"). If you cannot name at least one checkable
  invariant for it, it is not ready to draft.
- Every promise starts with a baseline exploration (no faults; proves the
  oracle observes the invariant at all). Named or nothing: nothing publishes
  without a key, so the baseline entry is never optional. Exploration keys
  are unique **project-wide**, so name it `<promise-stem>-baseline` (e.g.
  `acked-appends-baseline`), never bare `baseline`.
- Quote any frontmatter value containing free text — `provenance`,
  descriptions with colons/quotes/dashes. An unquoted `: ` inside a scalar
  is a YAML error the CLI only surfaces at publish time, which is the worst
  moment to find it. Self-check: the file must round-trip through a YAML
  parser at write time.
- Mark an entry `ready` only when the executor-contract fields are complete
  (spec-format lint rule 4) **and it has passed strategy-critic** (gate at
  ready — see [critics.md](critics.md)).
  A ready entry is a critic-validated contract; executors rarely bounce it.
- **The strategy-critic must read the SUT's source, not review abstractly.**
  Its brief: verify each fault window is actually reachable (cite
  file:line for the mechanism), check defaults the adversarial model
  depends on, and name the missing higher-value attack. On S2 every piece
  of critic value was source-verified fact — the ack-gating mechanism, a
  wrong flush-interval assumption, an implemented-but-hedged feature, and
  a new promise found in a startup comment.
- If the executor would have to invent the adversarial model, fault trigger,
  oracle, or replay plan, the entry stays `planned`.
- Keys are forever: kebab-case, unique project-wide, never renamed after an
  official run has published under them. Choose them like API names.

## How many named explorations

The number of named explorations under a promise = the number of distinct
fault models strategy-critic can name — the real ways the guarantee breaks.
Not one, not infinite. Emulate strategy-critic for set completeness before
marking entries ready: "you have a concurrency attack but no
retry-after-timeout, no partial-failure-mid-write, no duplicate-replay one."

**Ladder floor:** a promise is not *covered* until at least three rungs have
run — `<stem>-baseline`, plus at least one adversarial exploration, plus at
least one fault-boundary exploration — or strategy-critic has certified the
surface genuinely smaller (record that certification in the promise prose).
One-exploration promises (S2 shipped two of its promises with a single rung
each) are exactly the thin coverage this floor flags. An under-floor promise
**counts as producible work** for the stop condition: its missing rungs belong
in the backlog, so exhaustion can never be declared over its head.

Workload-file choice follows execution shape, not entry count: reuse one file
for entries sharing promise + setup + dependency/build profile + state model +
oracle family; new file only when one of those changes. Never mark an entry
ready with only "extend existing workload" — name the file and the
selector/command in the entry.

## Search / design loop

1. Read `.workers/map.md` for represented areas and durable evidence.
2. Read `.workers/backlog.md` — summary header + top ~10 active entries. If
   the backlog is thin (fewer than ~10 active entries above threshold),
   refresh the scout fan-out before planning.
3. Read existing promise files for harvested surfaces and open directions.
4. Read linked runs (`.workers/runs/*.md`) and findings.
5. Inspect target code, docs, tests, runtime setup, recent churn, known
   failures — via scouts on first contact / map refresh, directly otherwise.
6. Emulate bug-archeology, surface, fault-model, oracle, and feasibility
   critics. Weight by bug-likelihood (concurrency, state machines,
   idempotency, partial failure, ordering, boundaries) — not even coverage.
7. Promote from the backlog top (recording skips); write the batch.
8. Update `.workers/map.md` only for durable rows (new area, promoted
   finding, run link); update the backlog (insertions, retirements,
   compaction if due) and its summary header.

## Triage (when the dispatcher routed you here on a re-plan trigger)

1. Read the executor bounce-backs (`result: blocked` + `reason`) and new run
   evidence since your last episode.
2. Classify each: green evidence, bug candidate, historical finding,
   fixed-upstream, environment-sensitive, harness issue, setup blocker, or
   regression guard. Update `freshness` and `reported` accordingly.
3. Update the promise file's evidence/finding/regression prose. Re-arm a done
   entry (set `status: ready` again) when a target diff or a finding warrants
   a re-run.
4. On target-ref refresh: findings whose upstream fix merged flip to
   `freshness: regression-guard` — their explorations keep running as guards.
5. Clear the re-plan trigger in `loop-state.md` before yielding.

## Diff-directed episodes (the release-gate leg)

The find-loop intercepts *bugs*. **Regressions** — code that worked in a
released version and broke on a new commit — are intercepted by a different
leg: when the target ref advances, the changed code is re-attacked *with
compute behind it*, before the change ships. This is the release gate, and it
is a producer episode with attached sweep budget, not a mere re-rank.

**Detection (mechanical, every episode entry).** `loop-state.md` records a
`last-scanned-sha` (the target ref the loop last planned against) and the
current `target-head-sha`. When they differ, new commits landed since the last
session:

1. Enumerate the changed files over the range —
   `git diff --name-only <last-scanned-sha>..<target-head-sha>` — and the
   commit subjects, so a behavioural change is distinguished from a
   comment/format-only one.
2. **Map each changed file to a `[path: <tag>]` locus**, then to the backlog
   rows and promises carrying that tag. The `[path:]` tags (spec-format
   §Backlog) are exactly this join: a changed file whose locus matches a
   corridor's tag makes that corridor a **changed corridor**. Record the
   mapping in `.workers/diff-scan.md` (changed file → path tag → area →
   affected corridors, plus the untouched paths as explicit controls) so the
   selection is auditable.
3. Set the **diff-directed re-plan trigger** (dispatcher row 4) naming the
   range, and yield to the dispatcher — which routes the next producer episode
   here.

**The episode (target the change; attach sweep budget).** A diff-directed
producer episode is scoped BY THE DIFF, not by the standing backlog order:

- **Re-rank the changed corridors up** — a corridor whose code just changed has
  a fresh reason to break (the change may have introduced a regression or an
  incomplete fix), so it outranks its cold standing score for this cycle.
- **Attach sweep budget to each changed corridor** — this is the leg's
  defining move. Do not merely re-rank: dispatch (or, if a real run is
  unavailable, mark `ready` with a concrete `depth`) a **sweep** exploration
  against each changed corridor — a superset run at meaningful depth that
  exercises the changed path. Re-open the promise per the strategy-critic
  question ("given this change, is there a new fault model?"); if yes, add a
  named exploration, else re-arm the existing one with a depth that widens
  coverage over the changed region. A finding whose upstream fix is in the
  diff flips to `freshness: regression-guard` and its exploration keeps running
  as the guard.
- **Leave untouched-area corridors OUT of the diff-directed selection** — a
  corridor on a path with no changed file in the range is not a release-gate
  target this cycle, *even if it sits at the backlog top by standing score*.
  The diff drives selection here; the standing pool resumes on the next
  ordinary (row 6) episode. Record untouched high-rank corridors as controls
  in `diff-scan.md`, do not sweep them.
- **Comment/format-only commits** touching a corridor's file are a weak diff
  target — record the judgment, but a no-behavioural-change commit does not by
  itself earn sweep budget.

**Close the range.** Advance `last-scanned-sha` to `target-head-sha`, clear the
diff-directed trigger, and update the diff-scan record — so the next session's
detection starts from the newly-scanned tip and the same commits are never
re-swept.

## Backfill mode (existing corpus → this format)

When the target already has a spec corpus (e.g. the DBOS work-items), a
producer episode does the conversion: map existing area/promise/rung-ladder
prose onto spec-format keys (legacy corpora say "rung" — here that is simply
a named exploration). Re-keying is judgment — fine-grained legacy "areas"
usually become promises under fewer page-level areas. Preserve finding
status, upstream links, and replay metadata; they map to `freshness`,
`reported`, and `replay` directly. Executor then re-runs each converted entry
officially (recorded seed = replay-confirmation).

## Yield

End every episode by updating `loop-state.md` (batch summary, counters,
cleared triggers) and returning to the dispatcher. Do not start executing —
even if an entry looks irresistible.
