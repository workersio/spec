# Producer episodes — model, candidates, batches

The producer owns intent: `usage-model.md`, `candidates.md`, and scenario
frontmatter. It writes no workload code. Two episode shapes: **model work**
(dispatcher row 4, and the very first episode on a fresh corpus) and **batch
emission** (row 6).

## First episode on a fresh corpus: write the usage model

The model answers one question with evidence: **how is this product actually
used?** Sources, in priority order: README/quickstarts (what the vendor tells
every new user to do), `examples/` and template apps, official docs' task
pages, integration tests (what the vendor thinks matters), issue tracker
(what real users actually did when it broke). Scout fan-out: 3–5 foreground
read-only subagents briefed from
[briefs/candidate-scout.md](briefs/candidate-scout.md), each assigned a
source class, returning persona/flow/event evidence — never conclusions
without a citation.

- **Personas** are any contract-holding actor: human roles, calling
  applications, the product's *own* background threads (a recovery sweeper, a
  compactor), and adversarial siblings (a second instance racing the first).
  `weight:` is op-mix share — when no traffic data exists, reason it from the
  docs' emphasis and say so in the citation (G6).
- **Flows** are named multi-step journeys with the product's *claims* attached
  as `invariants:`. A flow without an invariant is sightseeing, not a test
  (G3). Steps live in the flow driver; the model only declares meaning.
- **Events** are real-world interruptions (crash-restart, dependency outage,
  disk-full, redeploy, clock jump) with declared `amplification:` — how much
  more often than real life the sampler lands them (importance sampling made
  explicit, G6).
- **Modules** (G8): list every top-level SUT source module with
  `covered-by:` flows, `covered-by: api-explorer`, or `parked: <reason>`.
  This is the mapping floor rebuilt usage-native — an orphan module blocks
  the stop row. Orphans that no realistic flow touches feed the
  `api-explorer` rarity persona instead of being forgotten.

Gate before the model is trusted: **strategy-critic model audit**
([critics.md](critics.md)) — is this how the product is really used? which
persona/flow/event is missing? are the weights self-flattering?

## Candidates: ranked situations, not code seams

A candidate row is a *situation*: cast × flows × event × rung, scored by
`P(user hits it) × severity-if-broken × novelty` (0–100, calibrate against
the existing table; `threshold:` in the header gates row-1 stop). Two
sources, one table:

- `usage` — traffic-weighted: hot flows, realistic casts, events at their
  amplified rates. The front door; most rows.
- `api-floor` — rarity-weighted: the `api-explorer` persona walking
  inverse-traffic verb sequences (`scenario_gen.api_explorer_seq`), G8-orphan
  modules first. The corridor instinct, kept as a *sampler*, never a second
  structure (~30% of the mix by default; tune in `journal.md` config).

Rank interactions above solos once L0/L1 floors exist: the bugs that survive
a vendor's own suite live where flows *interact* (L2) and where events land
mid-flow (L3).

## Batch emission (row 6)

Take the top of `candidates.md`, emit **5–10 scenario files** (`status:
planned` → `ready` once G4-complete), recording skips with reasons. Every
batch passes **strategy-critic set audit**: distinct situations or five
re-skins of one? Then `check.py` must exit 0 — the batch does not count until
the compile is clean. Promote each used candidate row out of the table.

Rules of thumb:
- L0s are the cheap mandatory floor — but they exist to make L2/L3 reds
  attributable, not as the goal. Get every unparked flow to L0/L1, then spend
  the budget on interactions.
- `depth:` by rung: L0 10–20, L1/L2 30–50, L3 50–100, L4 small-N long runs.
- An event scenario needs its no-event sibling at a lower rung first —
  otherwise a red is unattributable.
- Casts stay small (2–5 actors). Mass without a working shrinker is noise;
  `scenario_gen.shrink` must stay able to walk any scenario down.

## Model refresh (row 4)

Triggers: thin candidates (<5 above threshold), staleness (no new red in K=5
episodes — the answer is a *better model*, not more depth), or an executor
bounce (`reason:` names a model gap: an undeclared persona, a wrong flow
invariant, a missing documented-error entry). Refresh = re-run the scout
fan-out on the weak spot, adjust personas/flows/events/weights, re-rank
candidates, critic-audit, clear the trigger, append the decision to
`journal.md`. Never silently re-weight — the audit line says what changed and
why.
