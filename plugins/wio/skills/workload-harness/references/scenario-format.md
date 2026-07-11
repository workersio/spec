# Scenario format — the frozen contract (.workers/ v2)

This file is the authoring contract. `check.py` (rules G1–G9) is its
mechanical enforcement; `lib/CONTRACT.md` is the runtime-facing twin. A
format change is real only when this file, `check.py`, and the tree change in
the same commit.

## The tree

```
.workers/
  usage-model.md    # THE spec — personas · flows(+invariants) · events · actor-model · modules
  candidates.md     # ranked scenario candidates; --emit maintains the header block
  scenarios/        # one file per named scenario — the unit that runs
  flows/            # flow drivers: flows_<target>.py with the FLOWS registry
  lib/              # copied from the skill at init; never hand-edited in the repo
  findings/         # crystallized, minimized reds — replay recipe + evidence
  journal.md        # rails/config + append-only episode log
  check.py          # the compiler; copied from lib/ at init
  build.sh          # wio prepare surface (vendors the SUT, builds the venv)
  recipes/          # dependency-service recipes copied at init (postgres, kafka, …)
```

Identity lives in frontmatter `key:`s only — never in paths. Every index
(candidates header, coverage tables) is compiled output (`check.py --emit`),
never input.

## usage-model.md

```yaml
---
target: dbos                        # -> flows/flows_dbos.py
runner: .workers/run-with-postgres.sh .workers/python-runtime.sh
                                    # command prefix for run_scenario.py
actor-model: process-parallel       # how concurrent actors exist in this product
personas:                           # any contract-holding actor: human role, app,
  checkout-shopper:                 # the product's own background thread, adversary
    weight: 0.6                     # op-mix share; MUST carry a citation (G6)
    flows: [pay, browse]
    citation: "README quickstart + examples/ dir"
  api-explorer:                     # the rarity sampler — inverse-traffic weights
    weight: 0.05                    # over the same verb inventory; G8 orphans feed it
    flows: []
    citation: builtin
flows:
  pay:
    invariants: [charged-exactly-once, order-terminal]   # the claims (G3)
    citation: "docs/checkout.md"
events:
  crash-restart:
    amplification: 20               # how much rarer-than-life this is amplified (G6)
    citation: "recovery is the product's core promise"
modules:                            # the usage-native module floor (G8)
  - {name: core/_core.py, covered-by: [pay, browse]}
  - {name: cli, parked: "no runtime surface reachable in sim"}
  - {name: _admin_server.py, covered-by: api-explorer}
---
prose: how this product is actually used, with evidence; persona narratives;
what the weights mean; what was deliberately left out.
```

The model is producer-owned. Flow *drivers* (`flows/flows_<target>.py`) are
executor-owned code implementing each declared flow once:

```python
class PayFlow:
    key = "pay"                                  # G2: bijection with the model
    invariants = ("charged-exactly-once", "order-terminal")
    documented = {"pay": (PaymentDeclined,)}     # errorcontract input
    bounds = {"pay": 30.0}                       # wallclock input (optional)
    def run(self, ctx): ...                      # acks/denials -> ctx.ledger

FLOWS = {"pay": PayFlow}
def make_sut(meta, seed): ...                    # owns SUT lifecycle; .stop()
EVENTS = {"crash-restart": fire_crash_restart}   # event key -> fire(sut)
```

## scenarios/<key>.md

```yaml
---
key: shoppers-vs-cancel-during-restart   # immutable, project-unique (G7)
rung: L2                                 # L0 solo | L1 contention | L2 interaction
                                         # L3 +world event | L4 horizon
cast: {checkout-shopper: 3, ops-admin: 1}
flows: [pay, cancel-mid-run]
event: {key: crash-restart, at: crashclock}      # optional
invariants: [charged-exactly-once, order-terminal]  # from the flows (G3)
depth: 50                                # seeds for wio simulate create
status: planned | ready | done           # ready requires G4 completeness
result: null | green | finding | void | blocked
replay: null                             # {run: <wio run id>, seed: N}
redproof: null                           # draft run id of the PASSED red-proof (G5)
story: >-
  One sentence a non-engineer can read.
---
prose: why this situation, what the red-proof planted, evidence notes.
```

Ladder discipline: a flow's L0 must be `done` before its L1 is `ready`, and
so on up. Rungs above L2 should stay a minority until the L0/L1 floor of
every unparked flow exists.

## candidates.md

```markdown
<!-- emit:begin -->   (check.py --emit rewrites ONLY this block)
counts + flow × rung coverage table
<!-- emit:end -->
threshold: 40

| score | cast | flows | event | rung | source | note |
|-------|------|-------|-------|------|--------|------|
| 72 | 3×shopper +admin | pay,cancel | crash-restart | L3 | usage | recovery is the core promise |
| 55 | 1×explorer | (rare verbs) | none | L0 | api-floor | G8 orphan sweep |
```

Scoring spirit: likelihood a real user hits it × severity if the invariant
breaks × how untested the interaction is. `source:` is `usage` (traffic-
weighted sampler) or `api-floor` (rarity sampler). Rows are pruned when
promoted to scenarios (the scenario file is then the record).

## findings/<key>-<n>.md

```yaml
---
key: charged-twice-on-restart-1          # unique (G7)
scenario: shoppers-vs-cancel-during-restart   # must exist (G7)
severity: data-loss | correctness | availability | wrong-error | cosmetic
minimized: {cast: {checkout-shopper: 1}, flows: [pay], depth: 1, seed: 17}
replay: {run: <id>, seed: 17}
status: held                             # held -> triaged -> filed (by the human)
story: >-
  The user sentence, updated to the minimal shape.
---
evidence: INVARIANT lines, the shrink path, what the bug is, suspected seam.
```

## journal.md

Starts with a `## config` section (rails: max loops, max runs, staleness K,
candidate threshold), then an append-only `## log` of episode lines:

```
- 2026-07-11T10:00Z e12 executor shoppers-vs-cancel L2 depth=50 -> RED seed=17 (finding)
```

Never rewrite history; corrections are new lines. Position is derived
(`check.py --status`), not remembered.
