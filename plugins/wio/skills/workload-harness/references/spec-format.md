# Spec Format — `.workers/` frontmatter contract

This is the single format contract of the harness. Two writers, one reader:

- **Writers:** `init` (scaffold) and the **producer** (areas, promises, named
  explorations). Executors only update mechanical fields (`status`, `result`,
  `replay`, `published`) and never touch identity or prose intent.
- **Reader:** the wio CLI. `wio simulate create --exploration <key>` resolves
  the key in these files, walks exploration → promise → area, and assembles
  the publication envelope sent on `explorations.create`. Nothing else ever
  parses this format — the server receives validated JSON only.

(`backlog.md` and `loop-state.md` are the exceptions: loop-internal state the
CLI never reads, versioned alongside the spec so breadth and dispatcher
position survive compaction.)

Because the CLI walk and the skill both depend on it, this format is frozen:
extending it with new fields is fine; renaming or re-keying existing fields is
a migration.

## Vocabulary

One term, one thing: an **exploration** is one `simulate create` batch. A
**named exploration** carries a durable `key` — it is the recurring attack on
a promise (the page row's unit; runs of the same key over time are its
history). An **unnamed exploration** is a draft: same verb, no key, invisible
on the page. There is no separate "rung" concept.

## Layout (inside the target repo)

```
.workers/
  map.md                    # factual index: target ref, areas, promoted findings
  backlog.md                # ranked candidate pool (producer-owned, see §Backlog)
  areas/<area-key>.md       # one file per area
  promises/<promise-key>.md # one file per promise (the corridor work-item)
  workloads/**              # workload code (executor-owned)
  runs/<exploration-key>.md # raw run evidence (executor-owned)
  loop-state.md             # dispatcher state (mechanical, see SKILL.md)
  build.sh, builds/         # existing wio prepare surface, unchanged
```

Flat directories; membership is declared in frontmatter (`area:` on a promise),
not encoded in paths. Keys are kebab-case, immutable once an official run has
published under them, and unique within their scope (area keys per project,
promise keys per project, exploration keys per project — project-wide
uniqueness is what lets `--exploration <key>` be the only flag).

## Area file — `areas/<area-key>.md`

```yaml
---
key: durability                 # identity (immutable)
title: Durability
description: One-line customer-facing summary shown on the status page.
order: 10                       # optional page ordering hint
---
# prose: what this area covers, boundaries, harvested-vs-open notes
```

Envelope mapping: `envelope.area = {key, title, description}`.

## Promise file — `promises/<promise-key>.md`

```yaml
---
key: no-lost-writes             # identity (immutable)
area: durability                # must match an existing areas/<key>.md
title: No lost writes
claim: >-                       # the falsifiable guarantee, one sentence
  Acknowledged writes survive crash and restart.
status: active                  # active | parked
provenance: docs/durability.md#guarantees   # where the product makes this claim
explorations:
  - key: no-lost-writes-baseline  # identity (immutable, project-unique — never bare `baseline`)
    title: No lost writes baseline
    description: No faults; proves the oracle observes the invariant at all.
    status: planned             # planned | ready | done
    result: null                # null | green | finding | blocked
    reason: null                # required when result: blocked
    workload: workloads/no_lost_writes.py
    command: python3 .workers/workloads/no_lost_writes.py --case baseline
    faults: []                  # fault model names for simulate create
    depth: 10
    replay: null                # after a run: {run: <runId>, case: <id>, seed: <int>}
    freshness: new-current      # new-current | historical | fixed-upstream | regression-guard
    reported: null              # when filed upstream: {issue: "#742", fix: "#744", state: open}
    published: null             # null | pending | <exploration id of the official run>
---
# prose (producer-owned): adversarial model, fault dimensions with trigger
# points and reachability evidence, oracle definition, workload plan.
# prose (executor-appended): execution/evidence notes, finding summary,
# regression notes — same sections the DBOS corpus proved out.
```

Wire mapping (deployed shape, 2026-07-04): an official run sends the full
publication envelope on `explorations.create` —
`envelope: {area: {key, title, description}, promise: {key, title, claim},
exploration: {key, title, description}}` — area key/title/description from
the area file, promise key/title/claim from this promise file, exploration
key/title/description from the entry. **Keys are on the wire and are the
identity**: the server upserts area and promise by explicit key, stores the
exploration's key/title/description on its row, and stamps every run with
the exploration display. The promise page groups runs into one scenario row
per exploration key. Exploration `title` is required to publish (it is what
the page shows).

## Backlog file — `backlog.md` (producer-owned, loop-internal)

The persistent ranked pool of candidate promises and attack corridors. Unlike
the rest of the tree, the wio CLI never reads it — it is loop state,
versioned in git so breadth survives compaction and session restarts. One
writer: the **producer** (scouts, critics, and verdict re-entries feed it
only through a producer merge). Executors never touch it.

```markdown
# Backlog
- active: 12
- areas: { reads: 5, durability: 4, config: 3 }
- top-score: 384
- threshold: 20        # stop/retire line — tune per project, here

## Active (sorted by score, descending)

| score | candidate | area | L·I·O·N·R/C | provenance | source | notes |
|-------|-----------|------|-------------|------------|--------|-------|
| 128 | quote-rebalance-tail — a rebalance racing an append can emit a torn tail frame | framing | 2·4·4·4·4/4 | "docs/framing.md#tail; parser.rs:118" | scout-docs | [path: parser.rs:unquote] feedback 2025-11-03: L 1→2 sibling-inherit path parser.rs:unquote (red@quote-escape-roundtrip) |
| 90 | lease-renewal-skew — a renewed lease can briefly overlap its predecessor's grace window | leases | 3·3·5·2·3/3 | "src/lease.c:88" | scout-runtime | [path: lease.c] skip 2025-11-01: needs restart harness first |

## Archive (no loop agent reads this)

- reads: 3 retired (seed-sweep variants — belong in the reads ladders)
- config: 2 retired below threshold 2026-07-06
```

- **Score** = `bug-likelihood × impact × oracle-strength × novelty ×
  reproducibility / cost`, each factor coarse 1–5. Precision is not the
  point; *ordering* is. Record the factors in the `L·I·O·N·R/C` column so a
  critic can challenge them, not just the total.
- **`L` is the only evidence-corrected factor.** L (bug-likelihood) starts
  as a producer guess and is thereafter **corrected by evidence** — it is the
  loop's one empirical prior, not a standing model opinion. Two evidence
  sources move it, both in [producer.md](producer.md): **sweep outcomes**
  (§Score feedback — what this loop found) and **user exposure** (§User-exposure
  — what the repo's own issue history shows real usage already found). The
  other five factors stay model-judged (impact, oracle-strength, novelty,
  reproducibility, cost are properties of the corridor, not of what evidence
  found). The rules that update L live in producer.md; the mechanics below only
  define where the evidence, the code-path tag, and the audit trail are
  recorded.
- **`path`** — a code-path tag (a stable slug for the smallest source locus a
  corridor attacks, derived from its `provenance` file — e.g. `parser.rs`,
  `lease.c:renew`, `recovery`), carried as a bracketed prefix in the
  `notes` column: `[path: <tag>]`. It is what makes shared-code-path
  adjacency mechanical — two rows share a path iff their tags match. Tags are
  generic loci (a file, a function family, a subsystem), never a bug name or
  a target-specific constant. A row with no attacked source locus (a pure
  contract/docs corridor) may omit it.
- **`feedback` / `exposure`** — dated one-line audit trails of every L change,
  appended to `notes`. Sweep-driven moves are `feedback` lines:
  `feedback 2025-11-03: L 3→5 red@quote-escape-roundtrip (own)` or
  `feedback 2025-11-03: L 1→2 sibling-inherit path parser.rs:unquote` or
  `feedback 2025-11-07: L 5→4 decay 4× all-green`. Issue-history-driven moves
  are `exposure` lines carrying the cited counts:
  `exposure 2025-11-02: L 2→3 parser.rs:unquote (5 confirmed bugs, churn 12; issues/issue-history.md)`.
  Either trail is what a critic audits to challenge an L move — an L that
  changed with no `feedback`/`exposure` line is a hand-edit and is suspect.
- **`source`** is provenance of the candidate itself: `scout-<beat>`,
  `critic`, `producer`, or `verdict-reentry`.
- **Granularity:** entries live at promise / attack-corridor level.
  Variations (another seed, parameter, or depth) belong in the promoted
  entry's exploration ladder, never as separate rows.

**Hygiene — the file must never outgrow agent comprehension:**

1. Always sorted by score; the summary header (active count, per-area
   counts, top score, threshold) always current. Readers consume the header
   plus the **top ~10 rows only** — never the tail, never the archive.
2. **Dedup at insert time.** A candidate matching an existing entry updates
   that row's score/provenance; it never adds a sibling. Scouts' shards are
   deduped by the producer during the merge.
3. **Compaction is a producer duty.** When the active section exceeds ~30–40
   entries: merge duplicates, retire entries below threshold. Retired items
   roll up to **one line per area** in the archive section, which no loop
   agent reads.
4. Terminal outcomes: **promotion deletes the row** (the promise file's
   `provenance` carries the origin); **stop-corridor / retirement** rolls
   into the archive with a reason. Skipped-over entries stay active with a
   dated `skip:` note.

## Lint rules (CLI enforces at `--exploration`; producer self-checks at write)

1. The key resolves to exactly one entry across all promise files —
   duplicates are an error, not a warning.
2. The promise's `claim` and `title`, the entry's `title`, and the area file
   for `area:` must exist and be non-empty. A spec that can't fill the
   envelope can't publish.
3. Every promise carries at least one named exploration (`baseline` minimum)
   before any official run — named or nothing; there is no anonymous
   publication.
4. `status: ready` requires the executor-contract fields: `workload`,
   `command`, `faults` (may be `[]`), `depth`, and prose covering fault model,
   oracle, and replay plan. If the executor would have to invent any of
   those, the entry stays `planned`.
5. Frontmatter must parse as YAML at write time. Quote free-text values
   (`provenance`, descriptions containing `: `, quotes, or dashes) — the CLI
   surfaces a YAML error only at publish time, after the batch is written.

## Field semantics worth pinning

- **Identity vs decoration.** `key` never changes; it is the only identity.
  Titles, `claim`, and descriptions are decoration — the page shows the
  latest publish, and retitling is a reword, not a migration (the CLI warns
  on `key != slug(title)` but publishes). Renaming a *key* is the migration:
  it creates a new entity with empty history. History hangs off the promise
  and exploration keys, which is why workload re-authoring never orphans it.
- **`status` vs `result`.** `status` is the position (planned → ready →
  done); `result` is the verdict. `done` + `green` is a survived attack;
  `done` + `finding` is a red with `replay` filled; `done` + `blocked`
  carries `reason` for the producer's next sweep. These are plain fields, not
  a state machine — the loop is serial, nothing contends.
- **`replay` is evidence, not config.** Filled by the executor from the
  actual run (run ID, case, seed). Replay is pinned by **run id**
  (`wio workloads rerun <run-id>`), not by a create-time `--seed` (there is
  none today). An official run of a finding re-runs the batch at the same
  depth — the identical sequential seed set — and confirms the hit;
  publication *is* replay-confirmation.
- **`depth` is a superset knob, not a repeat count.** Seeds are sequential
  `1..depth`, so the same depth is the same seed set every time and a higher
  depth strictly contains a lower one. Bump `depth` (or change the workload)
  to widen coverage; re-running an unchanged entry at the same depth adds
  neither coverage nor evidence.
- **`published` is bookkeeping, `status: done` is the gate.**
  `.workers/publish.py` publishes every `done` exploration and rewrites
  `published:` with the new exploration id. If a publish fails, record
  `published: pending` and re-run the script — the server upsert is
  idempotent by key, so re-firing is always safe.
- **`freshness` + `reported`** carry the reported-vs-pending story (validated
  against the DBOS corpus): a filed finding whose fix merges upstream flips
  to `freshness: regression-guard` on the next target refresh, and its named
  exploration keeps running as a guard.

## What this format deliberately does not contain

- No owner / claim / lease / priority / next-action fields — that was the #82
  coordination layer; a serial loop has no contention. If a real executor
  fleet ever exists, coordination returns as a separate layer, not as spec
  fields.
- No run tallies or grid state — convex owns run facts; git owns intent and
  evidence. They join only through keys.
