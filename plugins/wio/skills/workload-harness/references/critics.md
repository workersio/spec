# Critic gates — re-aimed at scenarios

Two gates, same philosophy as v1: stop the drift toward useless passing
tests. Both run as **foreground, read-only** subagents briefed self-contained
from [briefs/](briefs/) — a dispatched critic reads only the target working
tree and this skill's directory. The main loop weighs the critique and
decides; critics advise, they never block mechanically (that is `check.py`'s
job).

## strategy-critic — before building (producer gate)

Two audits, one brief ([briefs/strategy-critic.md](briefs/strategy-critic.md)):

**Model audit** (first model + every row-4 refresh):
1. Is this how the product is *really* used? Name the most common real
   journey the model cannot express.
2. Which persona, flow, or event is missing — including the product's own
   background actors and adversarial siblings?
3. Are the weights self-flattering? (Do they concentrate mass where the
   harness is already strong, or where users actually are? Do citations
   support the numbers?)
4. **Refute every park.** For each `parked:`/`park:` reason in the model
   (modules, surfaces, events, flow modalities): is it an **environment
   fact** (this genuinely cannot run here — cite what fails) or a
   **self-imposed frame** (a belief about what the harness "is for")? Name
   the concrete experiment that would disprove the reason; if one exists and
   is affordable, the park is REFUTED and must be un-parked into candidate
   work. Survivors are reported per-park so the producer can stamp
   ` [audited eN]` on the reason — an unaudited park blocks stop.

**Set audit** (every row-6 batch):
1. Distinct situations, or re-skins? (Five casts of the same one flow is one
   scenario with depth, not five scenarios.)
2. Does the batch move the ladder — L0/L1 floors first, then interactions —
   or does it stack more solos on an already-floored flow?
3. Is anything here chasing a code seam instead of a situation? (Corridor
   thinking re-entering through the back door — send it to the api-floor
   sampler instead.)

## test-reviewer — after running (executor/crystallize gate)

Brief: [briefs/test-reviewer.md](briefs/test-reviewer.md). KEEP / REDO /
REMOVE on the scenario (and on a finding at crystallize time):

1. **Can this fail?** The red-proof run id is the required evidence (G5) —
   review that the *planted* violation is the kind a real bug would produce,
   not a strawman the oracle was tuned to.
2. **Real violation or oracle bug?** For a red: does the INVARIANT line trace
   to a flow invariant a user would recognize as broken (the `story:` reads
   true), or to harness misuse / an over-tight bound?
3. **Would the minimal shape convince a maintainer?** Cast, flows, depth,
   seed — nothing removable left, story updated, replay recipe runs.

A REDO on vacuity (VOID floors firing, ledger never written) goes back to
the driver, not the oracle: record what the flow must ack/observe. A REMOVE
prunes the scenario file and returns its candidate row with a note.
