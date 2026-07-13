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
  docs' emphasis and say so in the citation (G6). Two **builtin personas**
  (citation-exempt) must be declared in every model: `api-explorer` (the
  rarity sampler) and `contract-abuser` (the misuse persona: invalid spec,
  call-in-wrong-context, double-call, pathological identifiers,
  non-serializable arguments — its reds ride the error-contract oracle: the
  *promised* failure or a finding). The misuse floor is a stop gate: at
  least one done scenario must cast `contract-abuser`.
- **Flows** are named multi-step journeys with the product's *claims* attached
  as `invariants:`. A flow without an invariant is sightseeing, not a test
  (G3). Steps live in the flow driver; the model only declares meaning.
  Every flow declares its **`modalities:`** — for each of `sync`, `async`,
  `threaded`: `plan` (a done scenario in that modality is owed before stop)
  or `"park: <usage citation>"` (G10). A park reason must be an *environment
  or documentation fact* ("no async client is documented"), never a frame
  about the harness ("the sim drives the sync surface") — strategy-critic
  audits every park (below).
- **Surfaces** (G11, stop gate): the **documented-surface census**. Enumerate
  every API surface the docs/README/exports actually teach — decorators,
  client classes, methods, CLI verbs — at *documented-callable* granularity
  (modules are too coarse: a whole feature can hide inside one "covered"
  module file). Each surface gets `covered-by:` flow(s), a builtin persona,
  or `parked: <reason>`. A used surface with no flow is an orphan and blocks
  stop — that is the point.
- **Events** are real-world interruptions (crash-restart, dependency outage,
  disk-full, redeploy, clock jump) with declared `amplification:` — how much
  more often than real life the sampler lands them (importance sampling made
  explicit, G6).
- **Modules** (G8): list every top-level SUT source module with
  `covered-by:` flows, `covered-by: api-explorer`, or `parked: <reason>`.
  This is the mapping floor rebuilt usage-native — an orphan module blocks
  the stop row. Orphans that no realistic flow touches feed the
  `api-explorer` rarity persona instead of being forgotten.

- **Attention map (v0.2, run at model time and every refresh).** Once the
  surface census exists, write `.workers/attention-surfaces.json`
  (`[{name, tokens, files}]` — tokens chosen for regex distinctiveness,
  `_async` twins listed explicitly) and run the probe:

  ```
  python3 .workers/lib/attention.py --repo <SUT checkout> \
      --surfaces .workers/attention-surfaces.json \
      [--issues <frozen issue snapshot>] --cells > .workers/attention.md
  ```

  Commit the output. It is deterministic — an auditor re-running it must get
  identical bytes — and it is a *prioritizer*, never a coverage claim.

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
  inverse-traffic verb sequences (`scenario_gen.api_explorer_seq`) and the
  `contract-abuser` persona abusing contracts, G8-orphan modules and
  G11-orphan surfaces first. The corridor instinct, kept as a *sampler*,
  never a second structure. **The share is binding** (`api-floor-share:` in
  `journal.md` config, default 0.3): `check.py --status` blocks the row-1
  stop while done api-floor scenarios sit under share × done total. "Needs a
  new flow" is work, never a skip — every scenario carries `source: usage`
  or `source: api-floor` so the ledger is mechanical.

Rank interactions above solos once L0/L1 floors exist: the bugs that survive
a vendor's own suite live where flows *interact* (L2) and where events land
mid-flow (L3).

**The frontier rule (v0.2 — how depth is spent after the floors).** The
lattice is census surface × modality × mechanism × event; the six gates are
its mandatory floors. Every candidate row beyond the floors names the lattice
**cell** it attacks (note column), and the queue is ordered by the attention
map: highest-weight *uncovered* cell first — a cell users plausibly hit that
the vendor's suite never exercises **this way** outranks another solo on a
hammered cell. Two standing riders:
- **Coupling pairs:** flows that share state (same tables/columns/keys —
  statically visible in the drivers' verbs) are candidate L2 interactions;
  prioritize pairs whose *joint* cell is untested even when each solo is.
- **Depth escalation:** a cell that produced a near-miss (VOID that almost
  witnessed, an event that fired but found nothing at depth N) earns one
  escalated re-visit (higher depth / +1 rung) before the frontier moves on.
There is no "model exhausted" while high-weight uncovered cells remain —
budget rails, not saturation feelings, end the search.

## Batch emission (row 6)

Take the top of `candidates.md`, emit **5–10 scenario files** (`status:
planned` → `ready` once G4-complete), recording skips with reasons. Every
batch passes **strategy-critic set audit**: distinct situations or five
re-skins of one? Then `check.py` must exit 0 — the batch does not count until
the compile is clean. Promote each used candidate row out of the table.

Rules of thumb:
- **Spend against the blockers first.** `check.py --status` prints the open
  STOP-BLOCKERS (unfinished flow×modality pairs, census orphans, api-floor
  deficit, unfired amplified events, missing misuse floor, unaudited parks,
  aim-debt: mapped oracle'd flows baselined green but never attacked).
  Those are pre-ranked work — a batch that ignores an open blocker to add
  another scenario on an already-covered flow×modality is misspent budget.
- **The aim-debt gate.** While any `aim-debt:` blocker is open, do not emit a
  new baseline/green-control scenario on a flow×modality that already has a
  done green there — a green run of a promise nobody has tried to break is not
  coverage. Rank the batch by `(mapped AND oracle-exists AND not-yet-aimed)`:
  aim the budget at the named flows, which draws the L1-cap / L3-event surplus
  into the under-served L2 flow-interaction attacks that catch the bugs a
  vendor's own suite misses. First-baseline-per-flow×modality (owed by
  modality parity for attribution) is still permitted; it is *additional*
  green controls that the gate holds back.
- Every modeled event with real amplification must *fire*: an event worth
  declaring (amp ≥ `event-min-amp`, default 10) with zero done scenarios
  blocks stop. Budget events across the mix — not everything on the single
  most-cited one.
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

## Park audit (every park, before it can permit a stop)

A park is a claim that testing something is impossible or worthless — the
most dangerous sentence in the corpus. Every park (`parked:` on a module,
surface, or event; `"park: …"` on a flow modality) must survive a
**strategy-critic refutation attempt** ([critics.md](critics.md)): the critic
tries to *disprove* the reason. Survivors get ` [audited eN]` appended to the
reason string (N = the auditing episode); `check.py --status` blocks stop on
any park without the tag. A refuted park is un-parked and becomes candidate
work in the same episode.
