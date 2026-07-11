#!/usr/bin/env python3
"""Bare-runnable selftest for scenario_gen.py (no pytest)."""
import os
import random
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scenario_gen as sg  # noqa: E402

FAILS = 0


def check(name, cond, detail=""):
    global FAILS
    if cond:
        print(f"PASS {name}")
    else:
        FAILS += 1
        print(f"FAIL {name} {detail}")


META = {
    "key": "shoppers-vs-cancel-during-restart",
    "rung": "L3",
    "cast": {"checkout-shopper": 3, "ops-admin": 1},
    "flows": ["pay", "cancel", "browse"],
    "event": {"key": "crash-restart", "at": "crashclock"},
}
MODEL = {
    "target": "stub",
    "personas": {
        "checkout-shopper": {"weight": 0.6, "flows": ["pay", "browse"]},
        "ops-admin": {"weight": 0.1, "flows": ["cancel"]},
    },
}


# --- determinism: same inputs twice -> identical PLAN line -------------------
p1 = sg.build_plan(META, MODEL, 7)
p2 = sg.build_plan(META, MODEL, 7)
check("determinism-line", p1.line() == p2.line(), p1.line())

# actor ids and count expand the cast
ids = [a.actor_id for a in p1.actors]
check("cast-expand", ids == ["checkout-shopper-1", "checkout-shopper-2",
                             "checkout-shopper-3", "ops-admin-1"], f"{ids}")

# L2+ flow-seq length is 2..5, drawn from the scenario flows only
lens_ok = all(2 <= len(a.flow_seq) <= 5 for a in p1.actors)
check("L3-seq-len", lens_ok, f"{[len(a.flow_seq) for a in p1.actors]}")
subset_ok = all(set(a.flow_seq) <= set(META["flows"]) for a in p1.actors)
check("flows-subset", subset_ok)

# persona weighting: ops-admin lists only 'cancel' among the scenario flows
admin = [a for a in p1.actors if a.persona == "ops-admin"][0]
check("persona-weight", set(admin.flow_seq) == {"cancel"}, f"{admin.flow_seq}")
# checkout-shopper lists pay+browse (not cancel) -> never draws cancel
shopper_flows = {f for a in p1.actors if a.persona == "checkout-shopper" for f in a.flow_seq}
check("persona-intersection", "cancel" not in shopper_flows and shopper_flows <= {"pay", "browse"},
      f"{shopper_flows}")

# event armed with an op index inside [1, total_steps]
total_steps = sum(len(a.flow_seq) for a in p1.actors)
check("event-armed", p1.event is not None and 1 <= p1.event.op_index <= total_steps,
      f"{p1.event}")
check("plan-line-event", f"crash-restart@op{p1.event.op_index}" in p1.line(), p1.line())

# --- cross-process determinism: identical PLAN line in a fresh interpreter ---
snippet = (
    "import sys; sys.path.insert(0, %r); import scenario_gen as sg; "
    "print(sg.build_plan(%r, %r, 7).line())" % (
        os.path.dirname(os.path.abspath(__file__)), META, MODEL)
)
out_a = subprocess.run([sys.executable, "-c", snippet], capture_output=True, text=True).stdout
out_b = subprocess.run([sys.executable, "-c", snippet], capture_output=True, text=True).stdout
check("cross-process-determinism", out_a == out_b and out_a.strip() == p1.line(),
      f"{out_a!r} vs {p1.line()!r}")

# --- different seeds -> different plans somewhere across 20 seeds ------------
lines = {sg.build_plan(META, MODEL, s).line() for s in range(20)}
check("seed-diversity", len(lines) > 1, f"{len(lines)} distinct")

# --- shrink: strictly-smaller valid plans, ending near-minimal --------------
plan = sg.build_plan(META, MODEL, 3)
sizes = [plan.size()]
steps = 0
cur = plan
while True:
    nxt = next(iter(sg.shrink(cur)), None)
    if nxt is None:
        break
    # each candidate strictly smaller and valid
    if not (nxt.size() < cur.size()):
        check("shrink-monotone", False, f"{nxt.size()} !< {cur.size()}")
        break
    if not (len(nxt.actors) >= 1 and all(len(a.flow_seq) >= 1 for a in nxt.actors)):
        check("shrink-valid", False, f"invalid candidate {nxt.line()}")
        break
    sizes.append(nxt.size())
    cur = nxt
    steps += 1
    if steps > 1000:
        break
else:
    pass
check("shrink-monotone", all(sizes[i] > sizes[i + 1] for i in range(len(sizes) - 1)),
      f"{sizes}")
check("shrink-near-minimal", cur.size() == 2 and len(cur.actors) == 1
      and len(cur.actors[0].flow_seq) == 1, f"final size={cur.size()} {cur.line()}")

# every shrink candidate is a valid plan
allcands = list(sg.shrink(plan))
check("shrink-nonempty", len(allcands) > 0)
check("shrink-all-valid", all(len(c.actors) >= 1 and all(len(a.flow_seq) >= 1
      for a in c.actors) for c in allcands))

# --- api_explorer_seq inverse-weights: rare sampled more than hot -----------
verbs = ["hot", "warm", "rare"]
traffic = {"hot": 100.0, "warm": 5.0, "rare": 0.05}
rng = random.Random(1234)
draws = sg.api_explorer_seq(MODEL, verbs, traffic, 2000, rng)
counts = {v: draws.count(v) for v in verbs}
check("api-explorer-inverse", counts["rare"] > counts["hot"], f"{counts}")
check("api-explorer-len", len(draws) == 2000)
# determinism of the sampler under a fixed rng
rng2 = random.Random(1234)
draws2 = sg.api_explorer_seq(MODEL, verbs, traffic, 2000, rng2)
check("api-explorer-determinism", draws == draws2)

print("SELFTEST", "FAIL" if FAILS else "OK")
sys.exit(1 if FAILS else 0)
