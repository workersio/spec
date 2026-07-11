#!/usr/bin/env python3
"""scenario_gen -- the grammar sampler + shrinker for one scenario.

Ships with the wio workload-harness skill; copy into the repo's .workers/lib/.

Design contract (see CONTRACT.md §scenario_gen.py):
  * ``build_plan(meta, model, seed) -> Plan`` expands a scenario's ``cast`` into a
    concrete list of actors, assigns each actor a flow sequence drawn from the
    scenario's ``flows:`` weighted by the persona's declared flow weights in the
    usage model, and (when the scenario carries an ``event:``) arms that event at a
    seed-chosen op-index over crashclock's declared timing space. A Plan is PURE
    DATA -- a dataclass -- and renders to one machine-parseable line.
  * DETERMINISM is the whole point: every random draw goes through
    ``genlib.seeded_rng(root, label)`` (never the global ``random`` module and never
    wall-clock), so the SAME ``(meta, model, seed)`` yields a byte-identical PLAN
    line in every process on every machine. The root seed folds the scenario key
    and the case seed, so a different seed sweeps a different plan while a re-run of
    the same case reproduces it exactly.
  * ``shrink(plan)`` is the delta-debug generator: it yields strictly-smaller but
    still-valid candidate plans (drop an actor, then drop a flow from an actor's
    sequence), so a caller that keeps re-running can walk a red plan down toward a
    near-minimal reproducer.
  * ``api_explorer_seq`` is the rarity sampler: it draws a verb sequence with
    INVERSE-traffic weights over the same verb inventory, so cold-path verbs the
    real traffic almost never exercises get sampled the MOST -- the api-explorer
    persona's whole job.

The grammar sampled here is product-agnostic: personas, flows, verbs and events are
opaque tokens the usage model supplies. No product nouns live in this module.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

import crashclock
from genlib import root_seed_from, seeded_rng

API_EXPLORER = "api-explorer"


# ---------------------------------------------------------------------------
# Plan model (pure data)
# ---------------------------------------------------------------------------

@dataclass
class Actor:
    """One concrete actor: a persona instance and its drawn flow sequence."""

    actor_id: str
    persona: str
    flow_seq: list[str] = field(default_factory=list)


@dataclass
class EventArm:
    """A scenario event armed at a seed-chosen point in a declared timing space.

    ``op_index`` is the merged-op-stream index (a count of ``ctx.step`` barriers)
    at which the runner fires ``EVENTS[key](sut)``. ``point`` retains crashclock's
    full timing dict for replay/triage; ``op_index`` is its ``K`` projection.
    """

    key: str
    at: str
    op_index: int
    point: dict = field(default_factory=dict)


@dataclass
class Plan:
    """The concrete, deterministic expansion of a scenario for one seed."""

    seed: int
    actors: list[Actor] = field(default_factory=list)
    event: Optional[EventArm] = None

    # -- machine-parseable rendering ---------------------------------------
    def line(self) -> str:
        """The single PLAN line the runner prints and sweep-triage greps.

        ``PLAN seed=<n> actors=<id:persona,...> flows=<id=f1+f2;id2=f3> event=<key@point|none>``
        """
        actors = ",".join(f"{a.actor_id}:{a.persona}" for a in self.actors)
        flows = ";".join(f"{a.actor_id}={'+'.join(a.flow_seq)}" for a in self.actors)
        if self.event is not None:
            event = f"{self.event.key}@op{self.event.op_index}"
        else:
            event = "none"
        return f"PLAN seed={self.seed} actors={actors} flows={flows} event={event}"

    def size(self) -> int:
        """Total actors + total flow steps -- the shrink monotonicity measure."""
        return len(self.actors) + sum(len(a.flow_seq) for a in self.actors)


# ---------------------------------------------------------------------------
# Weighted flow sampling
# ---------------------------------------------------------------------------

def _flow_weights(scenario_flows: list[str], persona_flows) -> list[tuple[str, float]]:
    """Weight each scenario flow by the persona's declared flow weights.

    ``persona_flows`` may be a plain list (``[pay, browse]`` -> weight 1 each) or a
    ``{flow: weight}`` mapping. The weighting is over the INTERSECTION of the
    scenario's ``flows:`` and the persona's declared flows; if the persona lists
    none of this scenario's flows, the draw is UNIFORM over the scenario flows (an
    actor still has to do *something* in the scenario it was cast into).
    """
    if isinstance(persona_flows, dict):
        eligible = [(f, float(persona_flows.get(f, 0.0))) for f in scenario_flows]
        eligible = [(f, w) for f, w in eligible if w > 0.0]
    else:
        pf = set(persona_flows or [])
        eligible = [(f, 1.0) for f in scenario_flows if f in pf]
    if not eligible:
        eligible = [(f, 1.0) for f in scenario_flows]
    return eligible


def _weighted_draw(rng: random.Random, pairs: list[tuple[Any, float]]) -> Any:
    """Draw one item from a ``(value, weight)`` table using ``rng`` (seed-stable)."""
    total = sum(w for _, w in pairs)
    if total <= 0.0:
        return pairs[rng.randrange(len(pairs))][0]
    r = rng.random() * total
    acc = 0.0
    for val, w in pairs:
        acc += w
        if r < acc:
            return val
    return pairs[-1][0]


# ---------------------------------------------------------------------------
# build_plan
# ---------------------------------------------------------------------------

def _plan_root(meta: dict, seed: int) -> int:
    """Root seed for this (scenario, case). Folds the immutable scenario key so two
    different scenarios at the same seed sweep different plans, while a re-run of the
    same (key, seed) reproduces byte-identically."""
    key = str(meta.get("key", ""))
    return root_seed_from(f"scenario:{key}:{seed}")


def build_plan(meta: dict, model: dict, seed: int) -> Plan:
    """Expand a scenario's frontmatter into a concrete, deterministic Plan.

    Deterministic under ``seed`` (all randomness via ``seeded_rng``): expand the
    ``cast`` into actor ids ``<persona>-<i>``, draw each actor a flow sequence
    (length 1..3 for L0/L1, 2..5 for L2+) weighted by the persona's flows, and arm
    the scenario ``event:`` (if any) at a seed-chosen op index.
    """
    root = _plan_root(meta, seed)
    rung = str(meta.get("rung", "L0")).upper()
    lo, hi = (1, 3) if rung in ("L0", "L1") else (2, 5)

    cast = meta.get("cast") or {}
    scenario_flows = list(meta.get("flows") or [])
    personas_model = model.get("personas") or {}

    actors: list[Actor] = []
    # Iterate personas in sorted order so actor id numbering is process-independent
    # regardless of dict insertion order.
    for persona in sorted(cast):
        count = int(cast[persona])
        pconf = personas_model.get(persona) or {}
        pairs = _flow_weights(scenario_flows, pconf.get("flows", []))
        for i in range(1, count + 1):
            actor_id = f"{persona}-{i}"
            n = seeded_rng(root, f"flowlen:{actor_id}").randint(lo, hi)
            frng = seeded_rng(root, f"flowseq:{actor_id}")
            if scenario_flows:
                seq = [_weighted_draw(frng, pairs) for _ in range(n)]
            else:
                seq = []
            actors.append(Actor(actor_id, persona, seq))

    event = _arm_event(meta, root, actors)
    return Plan(seed=seed, actors=actors, event=event)


def _arm_event(meta: dict, root: int, actors: list[Actor]) -> Optional[EventArm]:
    """Arm the scenario ``event:`` at a seed-chosen op index over crashclock's
    op-index space. Absent ``event:`` -> None. The op-index space runs over the
    merged op stream, whose length we proxy by the total planned flow steps."""
    ev = meta.get("event")
    if not ev:
        return None
    if isinstance(ev, dict):
        key = str(ev.get("key", "event"))
        at = str(ev.get("at", "crashclock"))
    else:
        key, at = str(ev), "crashclock"
    total_steps = sum(len(a.flow_seq) for a in actors)
    hi = max(1, total_steps)
    space = crashclock.op_index(f"event:{key}", 1, hi)
    ev_seed = seeded_rng(root, "event").getrandbits(32)
    point = crashclock.offsets(ev_seed, space)
    return EventArm(key=key, at=at, op_index=int(point["K"]), point=point)


# ---------------------------------------------------------------------------
# shrink
# ---------------------------------------------------------------------------

def shrink(plan: Plan) -> Iterator[Plan]:
    """Yield strictly-smaller, still-valid candidate plans.

    Order (biggest reduction first): drop one actor (while >1 actor), then drop one
    flow from an actor's sequence (while that sequence has >1 flow). Every candidate
    is a valid Plan (>=1 actor, every actor >=1 flow); the caller re-runs each and
    keeps the smallest still-red. Iterating "take the first candidate, repeat" walks
    a plan down to the near-minimal 1-actor / 1-flow reproducer.
    """
    # 1) drop an actor
    if len(plan.actors) > 1:
        for i in range(len(plan.actors)):
            actors = [a for j, a in enumerate(plan.actors) if j != i]
            yield Plan(plan.seed, actors, plan.event)
    # 2) drop a flow from an actor's sequence
    for i, a in enumerate(plan.actors):
        if len(a.flow_seq) > 1:
            for k in range(len(a.flow_seq)):
                new_seq = a.flow_seq[:k] + a.flow_seq[k + 1:]
                actors = list(plan.actors)
                actors[i] = Actor(a.actor_id, a.persona, new_seq)
                yield Plan(plan.seed, actors, plan.event)


# ---------------------------------------------------------------------------
# api_explorer_seq -- the rarity sampler
# ---------------------------------------------------------------------------

def api_explorer_seq(model: dict, verbs: list[str], traffic: dict[str, float],
                     length: int, rng: random.Random) -> list[str]:
    """Draw a verb sequence with INVERSE-traffic weights over the verb inventory.

    A verb the real traffic exercises heavily (high ``traffic``) gets a LOW weight;
    a cold-path verb (low traffic) gets a HIGH weight, so over many draws the rare
    verbs dominate -- the api-explorer persona probes the corners real personas skip.
    Verbs absent from ``traffic`` inherit the minimum observed traffic (treated as
    rare). ``rng`` (a ``random.Random``) makes the draw seed-stable.
    """
    if not verbs or length <= 0:
        return []
    eps = 1e-6
    known = [traffic[v] for v in verbs if v in traffic]
    default = min(known) if known else 1.0
    pairs = [(v, 1.0 / (float(traffic.get(v, default)) + eps)) for v in verbs]
    return [_weighted_draw(rng, pairs) for _ in range(length)]


__all__ = [
    "API_EXPLORER", "Actor", "EventArm", "Plan",
    "build_plan", "shrink", "api_explorer_seq",
]
