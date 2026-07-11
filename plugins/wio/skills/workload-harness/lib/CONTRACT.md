# lib v2 — the scenario runtime contract (usage-first greenfield)

This file is the integration contract between the v2 modules. Every module
below ships in this directory, is copied verbatim into a repo's
`.workers/lib/` at init, and must run on **Python 3.12 stdlib only** (the wio
guest has no pip at run time). All modules follow the plane-member rules:
deterministic under a seed, `ORACLE_SELFTEST`-able, VOID anti-vacuity floors,
machine-parseable stdout lines, zero product nouns.

## The unit that runs

A **scenario** is a markdown file `.workers/scenarios/<key>.md` whose
frontmatter fully describes one situation:

```yaml
---
key: shoppers-vs-cancel-during-restart   # immutable, project-unique
rung: L0 | L1 | L2 | L3 | L4
cast: {checkout-shopper: 3, ops-admin: 1}   # persona -> actor count
flows: [pay, cancel-mid-run]                # flow keys from the usage model
event: {key: crash-restart, at: crashclock} # optional; omit for no event
invariants: [charged-exactly-once, order-terminal]  # inherited from flows
depth: 50                                   # seeds for wio simulate create
status: planned | ready | done
result: null | green | finding | void | blocked
replay: null                                # {run: <id>, seed: N} once evidence exists
redproof: null                              # draft run id of the passed red-proof
story: >-
  One user sentence a non-engineer can read.
---
prose: why this scenario, what the red-proof planted, evidence notes
```

One `wio` workload = one `(seed, fault)` = **one invocation** of:

```
python3 .workers/lib/run_scenario.py .workers/scenarios/<key>.md [--seed N] [--redproof]
```

`depth` in frontmatter is what the executor passes to
`wio simulate create --depth`; the runner itself executes exactly one case per
invocation.

## Module map and APIs (exact — other modules import these names)

### frontmatter.py (shared parser, no external yaml)
```python
def parse(text: str) -> dict        # YAML subset: scalars (str/int/float/bool/null),
                                    # inline lists [a, b], inline dicts {k: v, k2: 2},
                                    # dash lists, nested 2-space-indented dicts,
                                    # block scalars >- and |. Raises ValueError with
                                    # line number on anything else.
def load(path) -> tuple[dict, str]  # (meta, body) for a ----fenced markdown file;
                                    # meta == {} if no fence.
def dump(meta: dict) -> str         # re-emit the same subset, stable key order
                                    # (insertion order), round-trips parse(dump(m)) == m
```

### personaledger.py — the per-actor oracle
```python
class PersonaLedger:
    def __init__(self, actor_id: str): ...
    def acked(self, kind: str, key: str, value=None): ...
        # "the product told this actor: <kind>/<key> succeeded (with value)"
    def denied(self, kind: str, key: str, reason: str = ""): ...
        # "the product told this actor: <kind>/<key> was refused"
    def observe(self, kind: str, key: str, value=None, present: bool = True): ...
        # what a later re-read of the world shows for <kind>/<key>
    def check(self) -> list["Violation"]: ...
        # acked-but-not-observed  -> violation "acked_lost"
        # acked value != observed value -> "acked_mutated"
        # denied-but-observed-present  -> "denied_happened"
    def redproof_corrupt(self, rng): ...
        # plant a violation IN THE OBSERVATION CHANNEL ONLY: flip one acked
        # entry's observation to absent (or mutate its value). Never touches
        # the SUT. Prints "ORACLE_SELFTEST PLANTED ledger <actor> <kind>/<key>".
    @property
    def vacuous(self) -> bool  # True if zero acked+denied entries recorded

class Violation:  # dataclass: actor, code, kind, key, detail
```
Aggregation helper:
```python
def check_all(ledgers, emit=print) -> str
    # emits one line per actor:
    #   INVARIANT ledger_<actor> persona-ledger PASS|FAIL <n_violations> <first detail>
    # returns "GREEN" | "RED" | "VOID"  (VOID if ALL ledgers vacuous)
```

### errorcontract.py — every failure is the promised failure
```python
class ErrorContract:
    def __init__(self, documented: dict[str, tuple[type, ...]]): ...
        # op_label -> exception classes that are DOCUMENTED outcomes for that op
    @contextmanager
    def expect(self, op_label: str, outcome: str = "any"): ...
        # outcome "any": success or documented error both fine
        # outcome "must-fail": silent success is a violation ("silent_success")
        # a raised exception NOT in documented[op_label] -> violation
        #   "undocumented_error" (the 5xx class: raw driver errors, KeyError,
        #   AssertionError, product-internal exceptions). The exception is
        #   swallowed after recording (the flow continues) unless fatal=True.
    def check(self) -> list[Violation]
    def redproof_corrupt(self, rng)   # rewrite one recorded documented outcome
                                      # into an undocumented one (observation
                                      # channel only)
    @property
    def vacuous(self) -> bool         # zero ops recorded
def check_contract(contract, emit=print) -> str   # INVARIANT error_contract ... ; GREEN|RED|VOID
```

### wallclock.py — declared latency bounds
```python
class WallClock:
    @contextmanager
    def bound(self, label: str, max_s: float): ...   # records elapsed; > max_s = violation
    def check(self) -> list[Violation]
    def redproof_corrupt(self, rng)   # inflate one recorded elapsed past its bound
    @property
    def vacuous(self) -> bool
def check_clock(clock, emit=print) -> str   # INVARIANT wall_clock ... ; GREEN|RED|VOID
```

### scenario_gen.py — the grammar sampler + shrinker
```python
def build_plan(meta: dict, model: dict, seed: int) -> Plan
    # Deterministic (uses genlib.seeded_rng(root, label), never global random):
    # expand cast -> actor list [(actor_id, persona)], assign each actor a
    # flow sequence drawn from the scenario's `flows:` weighted by the
    # persona's flow weights in the usage model (uniform if absent),
    # choose event timing via crashclock's declared spaces when `event:` is
    # present. Plan is pure data (dataclass) and printable as one line:
    #   PLAN seed=<n> actors=<a:persona,...> flows=<per-actor comma lists> event=<key@point|none>
class Plan: actors: list[Actor]; event: EventArm | None
class Actor: actor_id: str; persona: str; flow_seq: list[str]

def shrink(plan: Plan) -> Iterator[Plan]
    # candidate smaller plans, in order: drop an actor -> drop a flow from an
    # actor's seq -> shorten seqs -> (depth handled by caller). Each candidate
    # is a valid Plan; caller re-runs and keeps the smallest still-red.

API_EXPLORER = "api-explorer"
def api_explorer_seq(model: dict, verbs: list[str], traffic: dict[str, float],
                     length: int, rng) -> list[str]
    # inverse-traffic weights over the same verb inventory (rarity sampler)
```

### run_scenario.py — the spine (executable)
```
python3 .workers/lib/run_scenario.py <scenario.md> [--seed N] [--redproof] [--list-plan]
```
Behavior, in order:
1. seed = --seed, else int(os.environ.get("WIO_SEED", 0)) or derived via
   genlib.root_seed_from(os.urandom hex); print `SEED <n>` first line.
2. Load scenario meta (frontmatter.load) and the usage model
   (`.workers/usage-model.md` — its frontmatter carries `target`, `personas`,
   `flows`, `events`; see check.py section).
3. Import the flow module `.workers/flows/flows_<target>.py` via importlib.
   It must export:
   ```python
   FLOWS: dict[str, type]      # flow key -> Flow class
   def make_sut(meta, seed) -> object   # owns SUT lifecycle; has .stop()
   EVENTS: dict[str, callable] # event key -> fire(sut) callable
   ```
   A Flow class:
   ```python
   class PayFlow:
       key = "pay"
       invariants = ("charged-exactly-once",)
       documented: dict[str, tuple]   # per-op documented exceptions (errorcontract)
       bounds: dict[str, float]       # per-step wall-clock bounds, optional
       def run(self, ctx): ...        # one execution for one actor; raises nothing
   ```
   FlowCtx passed to run():
   ```python
   ctx.actor_id; ctx.persona; ctx.rng          # per-actor seeded_rng
   ctx.ledger   # PersonaLedger for this actor
   ctx.errors   # shared ErrorContract
   ctx.clock    # shared WallClock
   ctx.sut      # the make_sut handle
   ctx.step(label)   # interleave barrier (no-op when 1 actor)
   ```
4. build_plan(); print PLAN line. `--list-plan` stops here (exit 0).
5. Liveness watchdog: SIGALRM at WATCHDOG_S (default 240, override env
   WIO_WATCHDOG_S) -> on fire print `INVARIANT liveness_watchdog liveness FAIL hang`
   and exit 1.
6. Run actors: 1 actor -> inline; >1 -> threads through interleave's
   scheduler (ctx.step == scheduler barrier), seed-driven release order.
   If plan.event: arm via crashclock timing (op-index space over the merged
   op stream) -> fire EVENTS[key](sut) at the armed point.
7. If --redproof: pick ONE oracle channel by rng (ledger of a random actor /
   errors / clock) and call its redproof_corrupt(rng) BEFORE checks; a
   redproof run MUST end RED — if checks come back green, print
   `ORACLE_SELFTEST FAIL oracle-swallowed-planted-violation` and exit 1
   (this is itself a red: the oracle is dead). If checks correctly FAIL,
   print `ORACLE_SELFTEST PASS` and exit 0. (So: redproof exit 0 == proof ok.)
8. Checks (always all): check_all(ledgers), check_contract, check_clock +
   terminal-state sweep hook if the flow module exports `sweep(sut) -> list[Violation]`.
9. Verdict: any FAIL -> `VERDICT RED`, exit 1. All vacuous -> `VERDICT VOID`,
   exit 3. Else `VERDICT GREEN`, exit 0. Always call sut.stop() in finally.
10. Setup problems (SUT failed to boot, module import failed): print
    `setup-block: <why>` to stderr, exit 44 — never a verdict.

### check.py — the compiler (lives at .workers/check.py in the repo; ships here as lib/check.py and is copied to .workers/check.py at init)
```
.workers/check.py [--status] [--emit]        # exit 0 clean, 2 on any G-failure
```
Reads the tree with frontmatter.py. `usage-model.md` frontmatter contract:
```yaml
---
target: dbos                       # -> flows/flows_dbos.py
actor-model: process-parallel      # free string, must be present
personas:
  checkout-shopper: {weight: 0.6, flows: [pay, browse], citation: "..."}
personas may include api-explorer: {weight: 0.05, flows: []}  # rarity sampler, exempt from G-flow rules
flows:
  pay: {invariants: [charged-exactly-once], citation: "..."}
events:
  crash-restart: {amplification: 20, citation: "..."}
---
```
Rules (each failure printed as `G<N> FAIL <file>: <detail>`):
- G1 every scenario's flows/cast personas/event exist in usage-model.md
- G2 flow keys in the model <-> FLOWS registry in flows/flows_<target>.py are
     a bijection (parse the file's `FLOWS = {...}` and Flow classes'
     `key=` by ast, do not import; also accept thin JS drivers declared as
     `js:<path>` values in the model — path must exist)
- G3 every flow carries >=1 invariant; every scenario invariant appears in
     one of its flows' invariant lists
- G4 status ready|done requires: cast, flows, depth, story, invariants all
     present and non-empty
- G5 status done + result green requires non-null `redproof:`  (HARD)
- G6 every persona weight has a citation; every event has amplification+citation
- G7 keys unique across scenarios/ and findings/; a key present in journal.md
     history may never disappear (append-only check: journal lines are never
     edited — verify via `git log -p` is out of scope; just check keys in
     findings/ still exist in scenarios/)
- G8 module floor: every top-level SUT source module (list supplied in
     usage-model.md frontmatter `modules:` with per-module status
     `covered-by: [flow keys] | api-explorer | parked: <reason>`) is covered
     or parked; orphans (absent from the list) FAIL — the executor keeps
     `modules:` current
- G9 every scenario/finding frontmatter parses; journal.md exists and starts
     with a `## config` section
--status: print which dispatcher row (1-6, see SKILL.md v2) fires now and why
--emit: rewrite the generated header block of candidates.md (between
        `<!-- emit:begin -->` and `<!-- emit:end -->`): counts by status,
        model coverage table (flow x rung grid of scenario counts)
```

## Selftests

Every module ships `test_<module>.py` runnable bare (`python3 test_x.py`,
no pytest), asserting: determinism (same seed twice == identical output),
redproof corruption flips green->red, VOID floors fire on empty usage,
and (frontmatter) round-trip. run_scenario gets a smoke test with a stub
flows module under a tmp dir.
