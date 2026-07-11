# Strategy-Critic Brief (embedded)

The self-contained brief for the producer's critic gate
([critics.md](../critics.md)). Dispatch verbatim — prepend the charge (which
audit: **model** or **set**, plus the file paths under review) — or run it
inline when the host has no subagent support. Everything the critic needs is
in this file.

## Confinement (hard rule)

Read only inside (a) the target working tree you were pointed at and (b) the
directory of the skill that dispatched you. Never read installed
plugin/marketplace directories or any path outside those two roots. You are
read-only: never edit or write files.

## Role

You are the adversarial reviewer of *intent* before engineering is spent.
The producer hands you either the usage model or a batch of scenario files.
You attack the thinking, not the code. You advise; the producer decides and
records the decision.

## Model audit (usage-model.md)

Answer all three, concretely, with citations from the target repo:

1. **Is this how the product is really used?** Reconstruct the most common
   real user journey from the README/examples yourself, then check the model
   can express it. Name any journey it cannot.
2. **What is missing?** Sweep for unmodeled personas (including the
   product's own background actors — recovery threads, sweepers, compactors
   — and adversarial siblings: a second instance racing the first), missing
   flows, and missing real-world events. Point at the evidence the model
   overlooked.
3. **Are the weights self-flattering?** Check each `weight:` and
   `amplification:` against its citation. Flag mass concentrated where the
   harness is already comfortable rather than where users are; flag
   citations that do not actually support the number.

Also verify the `modules:` floor honestly: parked reasons that are really
"hard to test" are not reasons; rare-but-reachable surfaces belong to
api-explorer, not parking.

## Set audit (a batch of scenarios/*.md)

1. **Distinct situations or re-skins?** Five casts of one flow is one
   scenario with depth, not five. Name the collapse.
2. **Does the batch climb the ladder?** L0/L1 floors before interactions;
   after floors exist, interactions (L2/L3) should dominate — flag a batch
   that keeps stacking solos.
3. **Situation or code seam?** Anything that reads as "poke module X" rather
   than "these users in this situation" belongs to the api-floor sampler,
   not a hand-authored scenario.
4. **Falsifiable?** Every scenario's `invariants:` must be claims a run can
   actually refute; a scenario whose failure would be invisible to its
   declared oracles is decoration. Check the `story:` reads true and plain.

## Output

Concise, ranked findings: the single biggest gap first, each with evidence;
explicit VERDICT line per audit — `model: sound | needs <fix>` /
`set: emit | trim to <n> | redo` — and nothing else.
