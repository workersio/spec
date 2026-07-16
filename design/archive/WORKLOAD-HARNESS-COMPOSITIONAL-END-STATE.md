# Workload Harness — Compositional Search End State

Status: canonical end-state draft pending the decisions in section 24  
Purpose: behavioral design to agree on before converting it into an agent skill  

This document describes the intended system, not the current skill. It defines
what people author, what the agent generates, how the search space is built, how
work is selected, what evidence counts, and when the search may stop.

No implementation should begin until the unresolved decisions at the end are
agreed. Once agreed, this document becomes the behavioral contract for the
skill, schema, compiler, generator, runner, checker, and tests.

## 1. The outcome

The workload harness should find important product bugs without requiring a
person to hand-author hundreds of scenarios.

People and agents author a small set of reusable **flow atoms** with trusted
invariants and composition metadata. The harness generates valid situations by
combining flows with actors, channels, execution forms, failure mechanisms,
events, state, scale, and environments.

The search system then:

1. builds an initial, sparse model of meaningful situations;
2. compiles explicit coverage and attack debt;
3. generates valid scenario candidates from reusable flow atoms;
4. enforces representative breadth before repeated depth;
5. ranks only the eligible frontier;
6. executes bounded systematic searches inside selected situations;
7. follows fresh evidence into neighboring situations;
8. shrinks credible failures; and
9. preserves every confirmed finding as a replayable artifact.

The central rule is:

> Coverage obligations decide where the harness is allowed to search.
> Attention decides which eligible situation runs next.

## 2. What is authored and what is generated

### Authored or reviewed

- Product personas and user/system goals.
- Reusable flow atoms.
- Product surfaces used by each flow.
- Falsifiable invariants.
- Flow inputs, outputs, effects, resources, and checkpoints.
- Supported access channels and execution modalities.
- Valid actor relationships.
- Applicable failure mechanisms, events, states, loads, and environments.
- Composition compatibility and conflict rules.
- Infrastructure facts and audited exclusions.
- Search-policy choices such as required floors and safety rails.

The agent may draft all of these from documentation and code. They remain
inspectable, cited, critic-reviewed model entries rather than hidden prompt
assumptions.

### Generated

- Flow sequences and parallel compositions.
- Same-flow contention.
- Cross-flow interactions.
- Actor casts consistent with declared topologies.
- Event placement at declared checkpoints.
- Environment matrices.
- Load profiles and geometric scale steps.
- Input values, seeds, schedules, and fault timings.
- Simpler control scenarios.
- Shrink attempts after a failure.
- Candidate priority and frontier views.
- Coverage, debt, concentration, and evidence reports.

The authoring unit is therefore not the final test. It is reusable behavior plus
the claims and constraints required to compose that behavior safely.

## 3. Canonical taxonomy

Every term has one meaning throughout the model, generator, scenario, run,
finding, and report.

| Term | Meaning | DBOS example |
|---|---|---|
| **Persona** | A contract-holding human or system role | application developer, worker, operator |
| **Flow** | A goal-oriented journey with one or more invariants | enqueue work and observe completion |
| **Invariant** | A falsifiable product claim | every acknowledged task executes exactly once |
| **Surface** | A documented capability or callable interface used by a flow | queue API, workflow API, stream API |
| **Actor topology** | Roles, identities, trust boundaries, and relationships among actors | two same-tenant workers; operator plus workers; two tenants |
| **Access channel** | The route through which a flow reaches product surfaces | SDK, CLI, HTTP API, web UI |
| **Modality** | The execution semantics used to invoke a surface | sync, async, threaded, multi-process, background |
| **Mechanism** | The hypothesized way an invariant may break | ownership race, retry exhaustion, completed-workflow reinvocation |
| **Event** | A time-local occurrence in the surrounding world | process crash, database outage, restart, clock jump |
| **State context** | A meaningful precondition at scenario start or attack time | fresh, claimed, acknowledged, completed, recovery-pending |
| **Load profile** | Actor count, operation rate, duration, data volume, and skew | 1,000 workers processing a burst of 10,000 tasks |
| **Environment profile** | Platform, dependency, version, and service context | FreeBSD+bhyve+SQLite; FreeBSD+bhyve+Postgres |
| **Scenario** | One named, executable, invariant-bearing composition | two workers recover one acknowledged task after a crash |
| **Run** | One scenario execution with concrete generated values | scenario X, seed 17, Postgres profile |
| **Finding** | A minimized, reviewed, replayable product failure | duplicate execution after queue-owner recovery |

### Required distinctions

- A flow is a goal, not a subsystem, event, modality, or mechanism.
- One flow may use multiple surfaces.
- One surface may participate in multiple flows.
- A UI, CLI, API, or SDK is an access channel; sync or async is a modality.
- Every scenario records one access channel. Products without an external
  UI/API/CLI/SDK use an explicit `direct-library` or `internal-driver` channel.
- Actor topology describes relationships; load profile describes scale.
- A mechanism describes how correctness may break; an event describes what
  happens in the world.
- State context and environment profile remain explicit. Neither is buried in
  runner commands or prose.

## 4. Product model

The product model establishes meaning before scenario generation:

```text
Personas
  └─ pursue Flows
       ├─ use one or more Surfaces
       └─ promise one or more Invariants

Actor topologies · Channels · Modalities · Mechanisms · Events · States
  └─ describe valid ways to challenge those flows

Load profiles · Environment profiles
  └─ describe scale and execution context
```

The relationships are typed and sparse. The harness does not assume that every
flow supports every topology, channel, modality, mechanism, event, state, load,
or environment.

Each relationship is classified as:

- `plan`: required and creates search debt;
- `covered`: satisfied by qualifying done evidence;
- `blocked`: valid but temporarily unreachable for a concrete reason;
- `park`: inapplicable or deliberately excluded with evidence and audit;
- `explore`: valid and eligible, but not a mandatory floor; or
- `unknown`: insufficient evidence; model refresh should investigate it.

## 5. Invariants and oracles

Invariant families are reusable across products. Concrete invariants bind those
families to product semantics.

| Family | Generic claim | Example binding |
|---|---|---|
| Safety | Something bad never happens | a task body never executes twice |
| Liveness | Progress eventually occurs | a workflow eventually becomes terminal |
| Durability | Acknowledged state survives failure | a completed result survives restart |
| Conservation | Nothing is silently created or lost | debits equal credits |
| Ordering | Observed order remains valid | committed stream records preserve order |
| Isolation | Actors cannot interfere outside the contract | one tenant cannot observe another tenant's queue |
| Authorization | Only permitted actors perform an action | only an allowed role invokes a protected workflow |
| Idempotency | Repetition does not duplicate effects | reinvocation reuses a completed workflow result |
| Compatibility | Supported versions interoperate | old and new workers agree on persisted state |
| Bounded resource use | Work terminates within declared limits | retry exhaustion exits instead of looping forever |

Every flow declares at least one concrete invariant. Every scenario runs:

1. the universal harness oracle plane, including liveness, terminal-state, and
   undeclared-error checks; and
2. every flow invariant applicable to that scenario's coordinate.

An applicable invariant may not disappear silently. If no executable oracle
exists, the model records **oracle debt** and the scenario cannot claim coverage.

## 6. Flow atoms

A flow atom is the smallest manually trusted unit of user-meaningful behavior.
It is reusable across many generated scenarios.

A flow atom declares:

```yaml
key: enqueue-and-complete
goal: Enqueue work and observe its completion.

personas: [worker]
surfaces: [queue, workflow]
channels: [python-sdk]
modalities: [sync, process-parallel]

inputs:
  - queue
  - task

outputs:
  - workflow-id
  - terminal-result

preconditions:
  - queue-exists
  - at-least-one-worker-running

effects:
  - workflow-created
  - task-claimed
  - result-persisted

resources:
  - system-database
  - queue
  - executor-ownership

checkpoints:
  - before-enqueue
  - after-enqueue
  - after-claim
  - after-ack
  - after-completion

invariants:
  - acknowledged-task-not-lost
  - task-body-executes-exactly-once
  - result-eventually-available

shrink:
  inputs: [task-count, payload-size]
  operations: [enqueue-count]
```

The flow implementation provides executable setup, operations, observations,
cleanup, and oracle hooks. It does not hard-code a particular actor count,
environment, event, or load unless those are intrinsic to the goal.

## 7. Composition algebra

The generator constructs scenarios using a small set of typed operators.

```text
flow(A)                         run one flow
sequence(A, B)                  run B after A using declared outputs/effects
parallel(A, B)                  overlap two compatible flows
race(A, A)                      contend on the same flow/resource
repeat(A, N)                    repeat a flow or operation
interrupt(A, event, checkpoint) place an event at a declared checkpoint
with_actors(A, topology)        bind roles and relationships
with_channel(A, channel)        select UI/API/CLI/SDK route
with_modality(A, modality)      select sync/async/thread/process semantics
with_state(A, state)            establish a relevant precondition
with_load(A, profile)           bind scale, rate, duration, volume, and skew
with_environment(A, profile)    select platform, services, and versions
```

Operators may nest:

```text
with_environment(
  interrupt(
    parallel(
      flow(enqueue-and-complete),
      flow(cancel-or-resume)
    ),
    process-crash,
    after-claim
  ),
  freebsd-postgres
)
```

### Composition validity

A composition is valid only when:

- required outputs satisfy downstream inputs;
- preconditions can be established;
- actor roles and relationships are compatible;
- channels and modalities are supported;
- shared resources are intentional and identified;
- effects do not make the scenario impossible before the intended interaction;
- event placement names a real checkpoint;
- the selected environment can provide required services;
- applicable invariants remain observable; and
- the composition has a deterministic shrink path.

Invalid mathematical combinations are never emitted merely to fill a grid.

### Independent and coupled flows

The generator uses both:

- **independent compositions**, which test non-interference, isolation, fairness,
  and shared-resource pressure; and
- **coupled compositions**, which test shared identities, state transitions,
  ownership, cancellation, recovery, and cross-surface semantics.

Resource/effect declarations help the generator identify likely coupling. A
critic may add product-specific coupling hypotheses that static metadata misses.

## 8. Scenario contract

A generated scenario records the complete semantic coordinate explicitly:

```yaml
key: queue-recover-after-ack-same-role
model-version: model-12
generator-version: generator-3
status: ready

composition:
  operator: interrupt
  child:
    operator: race
    flows: [enqueue-and-complete, enqueue-and-complete]
  event: process-crash
  checkpoint: after-claim

cast: {worker: 2}
actor-topology: same-role-contention
flows: [enqueue-and-complete]
surfaces: [queue, workflow]
channel: python-sdk
modality: process-parallel
mechanism: recover-after-ack
event: {key: process-crash, at: after-claim}
state: acknowledged-not-completed
load: semantic-small
environment: staging-freebsd-postgres

invariants:
  - acknowledged-task-not-lost
  - task-body-executes-exactly-once
  - result-eventually-available

control: queue-two-workers-no-crash
rung: L3
depth: 20
source: coverage-debt
```

The runner must not infer channel, mechanism, topology, state, load, or
environment from the scenario name, story, note, rung, or shell command.
The checker must also reject semantic coverage inferred only from seed count, a
baseline, an attempted-but-blocked run, or an attention score.

## 9. Rungs describe complexity, not identity

| Rung | Meaning | Typical composition |
|---|---|---|
| L0 | Attributable control | one flow, simplest topology, nominal mechanism |
| L1 | One explicit adversarial dimension | one flow plus race, retry, misuse, or reinvocation |
| L2 | Interaction | multiple actors, roles, tenants, versions, or flows |
| L3 | Event/state composition | an event or recovery/migration state lands during an attack |
| L4 | Horizon/load | high scale, rate, volume, repeated lifecycle, or soak |

A rung never substitutes for the explicit scenario coordinate.

## 10. Actor topology and scale

Actor topology and load profile are independent dimensions.

```text
Topology: same-role-contention
Load A: 2 workers
Load B: 100 workers
Load C: 1,000 workers
```

Small casts search semantic correctness and enable attribution. Large profiles
search limits, fairness, resource exhaustion, hot-key contention, thundering
herds, and tail behavior.

Scale grows geometrically from a small attributable control. Product limits and
environment capacity select the actual steps. For example:

```text
1 → 2 → 4 → 8 → 16 → 100 → 1,000
```

The displayed sequence is illustrative, not a universal contract value. The
generator skips meaningless steps, respects environment capacity, and stops
when evidence, a declared product limit, or a safety rail fires. Every large
profile declares how to shrink actor count, operation count, rate, duration,
data volume, and skew.

## 11. Environment matrices

Environment substitution reuses one semantic scenario across supported
profiles:

```text
same flow
same actors
same mechanism
same event timing
same seed
├─ FreeBSD + SQLite
└─ FreeBSD + PostgreSQL
```

The harness checks invariants independently in each profile and may add a
differential oracle. A behavioral difference is a search signal, not
automatically a product bug.

Environment matrices are applicability-driven. Pure CLI parsing does not need
automatic database duplication; queue ownership, recovery, transactions,
streams, notifications, and migrations often do.

Blocked profiles create infrastructure debt and do not count as covered.

When a valid candidate is blocked, the harness:

1. records the precise missing capability;
2. separates product, harness, and substrate evidence;
3. creates a named infrastructure obligation;
4. continues with another eligible situation when possible; and
5. restores the blocked situation to the frontier when the capability becomes
   available.

An approximation may run for learning, but it cannot satisfy the original
environment-specific obligation unless an audited policy explicitly declares
the environments equivalent for that invariant and mechanism.

## 12. Building the lattice

The lattice is a versioned, living model—not a complete grid invented upfront
and not an unrelated list improvised per workload.

### Initial lattice

Before the first workload, the producer inspects documentation, examples,
exports, code, environments, and known usage to draft:

- personas, flows, surfaces, and invariants;
- valid actor topologies, channels, and modalities;
- applicable mechanism families, events, and states;
- load and environment profiles;
- compatibility, coupling, and park hypotheses; and
- the initial search obligations.

Observed facts carry citations. Search hypotheses and policy choices are labeled
as such and reviewed by a critic.

### Progressive refinement

Runs change the model when they reveal:

- an unmodeled flow, surface, actor relationship, state, or environment;
- an incorrect applicability or park judgment;
- a new coupling between flows;
- an infrastructure requirement;
- a near-miss or divergence;
- a finding with meaningful neighboring situations; or
- stagnation indicating that the model is too narrow.

Each accepted change creates a new model version. Historical runs retain their
original model and scenario coordinates.

### Sparse compilation

The compiler materializes only valid obligations and candidates. It does not
enumerate the complete Cartesian product.

## 13. Search debt

Search debt is explicit work that must be satisfied or audited as parked before
the harness may claim model exhaustion. A blocked obligation remains debt; it
may explain a rail stop but cannot satisfy model exhaustion.

The compiler tracks:

- **mapping debt:** every documented surface maps to flows or an audited park;
- **oracle debt:** applicable invariants have executable oracles;
- **baseline debt:** every declared required flow × channel × modality tuple
  has a control; the model declares sparse valid tuples rather than requiring a
  full channel × modality product;
- **attack debt:** every green invariant-bearing flow receives a real attack;
- **actor-topology debt:** required relationships receive adversarial coverage;
- **channel debt:** required UI/API/CLI/SDK routes execute applicable flows;
- **modality debt:** required sync/async/thread/process forms are exercised;
- **mechanism debt:** required mechanism families actually attack applicable
  invariants;
- **event/state debt:** required events fire and required states are reached;
- **load debt:** planned scale profiles run after semantic prerequisites;
- **environment debt:** required profiles are reachable and exercised; and
- **exploration debt:** the configured open-exploration lane is not starved.

An attempted but blocked scenario pays no semantic debt.

## 14. Constrained frontier

Search selection always occurs in two stages.

### Stage A — determine eligibility

A candidate is eligible when it:

1. pays mandatory debt;
2. establishes a prerequisite control;
3. follows fresh evidence into a nearby coordinate;
4. crystallizes or minimizes a red; or
5. uses the reserved open-exploration budget.

Eligibility enforces:

- prerequisite controls;
- breadth across flows;
- breadth across topologies, channels, modalities, and mechanism families;
- required event/state and environment obligations;
- load prerequisites;
- per-flow and per-cell depth caps;
- infrastructure reachability; and
- red-first evidence handling.

### Stage B — rank eligible candidates

Attention may rank the eligible frontier using:

- evidence-backed user relevance;
- severity of threatened invariants;
- novelty relative to completed scenario coordinates;
- fresh run evidence such as a red, near-miss, hang, or divergence;
- shared-resource and cross-flow coupling;
- source-change or complexity evidence;
- vendor-test deficit for the exact situation;
- reachability and execution cost; and
- a weak, capped historical-issue prior.

No score may bypass unpaid mandatory debt. Attention is a priority order, never
a coverage claim.

## 15. Search portfolio

The finite budget contains three conceptual lanes:

1. **Coverage:** mandatory obligations and prerequisites.
2. **Evidence-driven depth:** near-misses, divergences, findings, and strongly
   coupled neighbors.
3. **Open exploration:** valid combinations the current model may undervalue.

The harness combines heuristics with bounded systematic search:

- heuristics select meaningful cells;
- pairwise or selected three-way covering arrays span applicable dimensions;
- property-based generators explore values inside a cell;
- deterministic schedule search explores concurrency;
- fault-time sweeps explore checkpoint boundaries;
- geometric ladders explore load;
- environment matrices search substrate differences;
- one-coordinate mutation explores finding neighborhoods; and
- reserved novelty/random search keeps the model falsifiable.

Global brute force is prohibited as a strategy. Systematic enumeration inside a
bounded meaningful region is encouraged.

## 16. Controls, execution, and attribution

Every generated attack has a simpler attributable control unless an equivalent
qualifying control already exists.

Examples:

```text
Control: one worker completes one queued task without interruption.
Attack: two workers race while one crashes after claim.

Control: a completed workflow is read once.
Attack: the completed workflow is reinvoked concurrently through the async API.
```

Each run records:

- exact model, generator, skill, target, and environment versions;
- scenario coordinate and composition tree;
- seed, schedule, fault timing, and generated inputs;
- control evidence;
- invariant and universal-oracle results;
- resource, terminal-state, and timing summaries; and
- blocked, void, green, or red classification.

## 17. Shrinking and findings

A credible red preempts unrelated new search until reproduced and classified.

The shrinker reduces, where applicable:

```text
flows
→ operators
→ events
→ actors
→ operations
→ schedules
→ rate and duration
→ data size and skew
→ environments, when the failure is not environment-specific
```

A finding is complete only when it has:

- a minimized composition;
- a violated invariant;
- a passing control;
- a replayable seed/schedule/fault recipe;
- exact target and environment versions;
- red-proof or equivalent oracle validation;
- product/harness/infrastructure classification; and
- neighboring candidate suggestions.

Confirmed findings generate adjacent candidates by changing one meaningful
coordinate at a time. They do not erase unpaid breadth obligations.

## 18. Facts, hypotheses, and policies

A finite search budget always contains opinions. The system makes them visible
and reversible instead of hiding them in prompts or scenario order.

| Class | Example | Change behavior |
|---|---|---|
| **Observed fact** | DBOS documents an async workflow API | cite and retain historically |
| **Search hypothesis** | async recovery may deadlock | revise freely with evidence |
| **Policy choice** | recovery must be attacked before queue depth | version and compare experimentally |
| **Unknown** | cross-version stream behavior is unclear | investigate through model refresh/exploration |

Changing a hypothesis or policy creates a new model/policy version, recompiles
debt and the frontier, and preserves historical evidence under its original
version.

The model is opinionated enough to act, explicit enough to audit, and reversible
enough to learn.

## 19. Agent operating loop

The eventual skill should make the agent execute this loop:

```text
1. Load model, policy, journal, evidence, and open debt.
2. If a red is uncrystallized, reproduce and shrink it.
3. If execution is in flight, resume it.
4. If the model is stale, thin, or contradicted, refresh and review it.
5. Compile valid obligations and candidate compositions.
6. Build the mechanically eligible frontier.
7. Rank only that frontier.
8. Generate the next scenario plus its control and shrink plan.
9. Validate the composition and oracles.
10. Execute bounded runs through wio.
11. Record evidence and update debt.
12. Expand around fresh evidence.
13. Repeat until debt is clear or a safety rail stops execution.
```

The loop must survive context compaction using versioned files and compiled
views. Conversational memory is never the source of truth.

## 20. Stop semantics

The harness may claim model exhaustion only when:

- no uncrystallized red exists;
- mapping and oracle debt are zero;
- required baseline and attack debt are zero;
- required topology, channel, modality, and mechanism debt are zero;
- required event, state, load, and environment debt are zero;
- no unaudited park exists;
- no required candidate is hidden behind an attention score;
- no above-threshold evidence-driven candidate remains;
- the open-exploration policy was honored; and
- all integrity and safety checks pass.

A run, cost, wall-clock, or context rail may stop execution earlier. A rail stop
reports every remaining debt and candidate and never claims coverage exhaustion.

## 21. Required inspectable views

The compiler should emit projections from one source of truth:

1. personas → flows → surfaces → invariants;
2. flow × channel × modality baseline/attack status;
3. flow × actor-topology status;
4. flow × mechanism-family status;
5. event × state firing status;
6. load progression and shrinkability;
7. environment reachability and differential coverage;
8. composition graph and shared-resource coupling;
9. open debt ordered by mandatory floor;
10. eligible frontier ordered by attention;
11. per-flow/per-cell budget concentration; and
12. findings with replay and neighboring candidates.

These are compiled views, not independent truth files.

## 22. Implementation completion criteria

The skill conversion is complete only when:

### Model and schema

- [ ] Every canonical term has one meaning across all files and messages.
- [ ] Flow atoms are goal-oriented, invariant-bearing, and reusable.
- [ ] Flows support multiple surfaces and surfaces support multiple flows.
- [ ] Topology, channel, modality, mechanism, event, state, load, and
  environment are explicit.
- [ ] Every taxonomy identity is unique and referentially valid across model,
  candidate, scenario, run, and finding.
- [ ] Invariant applicability and oracle debt are explicit.
- [ ] Composition inputs, outputs, effects, resources, and checkpoints are
  machine-checkable.
- [ ] The checker enforces coordinate applicability, prerequisites, and the
  distinction between blocked, parked, covered, explore, and unknown.

### Generation

- [ ] Typed operators generate sequence, parallel, race, interruption, actor,
  channel, modality, state, load, and environment variants.
- [ ] Invalid compositions are rejected with actionable reasons.
- [ ] Every attack has or reuses an attributable control.
- [ ] Every generated scenario has a deterministic shrink plan.
- [ ] Generation is deterministic from model version, policy, and seed.

### Search

- [ ] The compiler builds a sparse set of valid obligations and candidates.
- [ ] Coverage debt determines eligibility before attention ranking.
- [ ] Breadth is enforced across flows and required dimensions.
- [ ] Per-flow and per-cell concentration caps are mechanical.
- [ ] Attention cannot promote an ineligible high-score cell.
- [ ] Evidence earns depth without erasing mandatory breadth.
- [ ] Open exploration cannot silently collapse to zero.

### Execution and evidence

- [ ] Scenario and control execute through wio with exact provenance.
- [ ] Blocked runs pay no semantic debt.
- [ ] Applicable invariants and universal oracles run mechanically.
- [ ] Reds preempt unrelated work until classified and minimized.
- [ ] Findings retain complete coordinates and replay instructions.
- [ ] Environment differences are signals until an invariant proves a bug.

### Stopping and migration

- [ ] Model exhaustion requires zero mandatory debt.
- [ ] Rail stops report remaining debt without claiming exhaustion.
- [ ] Old scenario files either upgrade deterministically or fail with an
  actionable migration message.
- [ ] A rung is never silently converted into a mechanism or actor topology.
- [ ] Existing `cast` data gains an explicit topology relationship; large casts
  become load profiles rather than new topology identities.
- [ ] Existing valid modality/event identities and blocked/parked evidence are
  preserved.
- [ ] Historical scenarios remain readable under their original model version.
- [ ] Existing implicit fields are not converted into false explicit coverage.
- [ ] New coverage claims derive only from explicit new-schema evidence.
- [ ] Positive, negative, migration, and end-to-end tests cover every new gate.

## 23. Evaluation plan

Evaluate changes as separately attributable treatments:

1. current v0.1.8 behavior;
2. taxonomy and explicit-coordinate refactor;
3. compositional generation with equivalent ranking;
4. constrained frontier with current attention as tie-breaker; and
5. any future attention formula as a separate treatment.

Freeze each treatment before keyed evaluation. Compare:

- mapping retention;
- correct-mechanism aim;
- invariant-bearing attack breadth;
- generated-scenario validity;
- useful composition rate;
- novel replayable findings;
- false-red escapes;
- shrink success;
- blocked-budget waste;
- search concentration; and
- remaining debt at rail stop.

The first implementation should not combine the compositional refactor with a
new attention formula. Otherwise improved or degraded results cannot be
attributed cleanly.

## 24. Alignment decisions still required

Before converting this contract into the skill, agree on:

1. the exact flow-atom schema and implementation interface;
2. the initial universal invariant/oracle families;
3. the initial operator set and which nesting combinations are allowed;
4. how applicability is authored versus inferred;
5. the minimum mandatory breadth across mechanism families and topologies;
6. the default coverage/depth/exploration budget policy;
7. the environment-specific load policy and safety caps;
8. which model changes require critic review or human approval;
9. how generated scenarios are stored, regenerated, and versioned;
10. the compatibility/migration boundary for existing workload trees; and
11. the smallest DBOS prototype that proves the abstraction before the full
    skill conversion.
