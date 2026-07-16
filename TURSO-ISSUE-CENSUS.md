# Turso issue census — taxonomy field test (2026-07-15)

Research-agent categorization of the 200 most recent issues in
tursodatabase/turso (#7103–#7845, 2026-05-15→2026-07-14; repo total 2,499).
Supports: the v3 taxonomy (📜), depth-≤3 doctrine (📖), differential-oracle
strategy, and fleet-turso target selection. Companion: PRIOR-ART-AUTOPSY.md.

## Headline
153/200 = product bugs. Taxonomy verdict: **0% no-fit · 58% clean · 35%
ambiguous (concentrated, 3 fixable gaps) · 7% insufficient text.** With the
three amendments below, estimated ~80% clean.

## Distributions (n=153)
- Severity: correctness 45% · availability 21% · data-loss 20% · wrong-error
  12% · cosmetic 2%. Severity-weighted mass 407; data-loss = 29% of mass;
  ~⅓ of harm-weight sits in checkpoint/WAL/MVCC lifecycle code.
- Composition order: **pair 63% · solo 23% · triple+ 14%** (triples nearly all
  checkpoint/MVCC/restart lifecycle).
- Trigger: plain-input 58% · concurrency 22% · state-context 10% ·
  environment 4% · fault 4% · load 1%.
- Oracle: declared-correctness 41% · **differential vs SQLite 33%** ·
  universal-crash 20% · error-contract 5% · liveness 1%.

## The three taxonomy amendments (adopted into 📜)
1. **client-abandonment as an event type** — statement dropped at a yield
   point, single actor, no fault; Turso's biggest single bug family (~16
   issues, `partial execution` label). Expressible as
   interrupt(A, client-abandons, checkpoint) — new event, not new dimension.
2. **Severity precedence** — corruption of committed state dominates the
   crash that revealed it; "bricked but not lost" (data intact, inaccessible)
   = data-loss.
3. **Oracle axis** — add self-differential/metamorphic (optimized path vs own
   fallback); scope cross-differential to the compatibility-shared surface.
   Rater rule: in-repro setup = plain-input; pre-existing cross-session
   state = state-context.

## Strategic observations
- **Differential vs real SQLite catches 33% of all bugs** (68% of those are
  clean solo/pair plain-input SQL) — the cheapest strong oracle available;
  makes Turso an unusually attractive fleet target (oracle problem largely
  pre-solved on the shared surface). Ceiling: MVCC/FTS/encryption/CDC/sync
  are Turso-only → declared invariants (integrity_check, durability-across-
  reopen, acked-write-persists carry most of the 41%).
- **DST-escape evidence (the Antithesis-gap thesis, field-confirmed):**
  ~⅓ of bugs are self-reports from Turso's own tooling (simulator seeds,
  antithesis label, shuttle, io_memory_yield probes). The classes that
  ESCAPED to external users: (a) API-usage-pattern bugs invisible to pure
  SQL-script DSTs — undrained-cursor silent data loss family (#7260/7106/
  7345/7466), bindings races (#7794); (b) multiprocess WAL (#7213/7346/7340);
  (c) solo plain-input edges found by OUTSIDERS' differential fuzzers (R1–R13
  join series, JSON/pragma compat tools). Determinism without a semantic
  model misses exactly the semantic layer — our product thesis, in their
  tracker.
- **Pair dominance (63%)** = feature×feature interaction (ALTER×triggers,
  FTS×joins, checkpoint×reader) — direct support for compositional pairs as
  the mandated floor. Triple+ at 14% is fatter than the NIST prior suggests;
  nearly all triples are lifecycle stacks (checkpoint-fail → restart →
  operate), i.e., sequence-with-fault chains our algebra expresses at depth 3.
- Boundary class to decide before fleet-turso: unimplemented SQLite
  constructs under a "SQLite-compatible" promise — wrong-error bugs or
  feature requests? (#7296 etc.)

Full per-issue labels: the census agent's classify.csv (200 rows) in its
task workspace; regenerate via gh search API if needed.
