#!/usr/bin/env python3
"""Bare-runnable selftest for frontmatter.py (no pytest)."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import frontmatter as fm  # noqa: E402

FAILS = 0


def check(name, cond, detail=""):
    global FAILS
    if cond:
        print(f"PASS {name}")
    else:
        FAILS += 1
        print(f"FAIL {name} {detail}")


SCENARIO = """key: shoppers-vs-cancel-during-restart
rung: L3
cast: {checkout-shopper: 3, ops-admin: 1}
flows: [pay, cancel-mid-run]
event: {key: crash-restart, at: crashclock}
invariants: [charged-exactly-once, order-terminal]
depth: 50
status: planned
result: null
replay: null
redproof: null
story: >-
  Three shoppers check out while an admin cancels a stuck order and the
  service crash-restarts; every shopper is charged exactly once.
"""

m = fm.parse(SCENARIO)
check("scalar-int", m["depth"] == 50)
check("null", m["result"] is None)
check("inline-dict", m["cast"] == {"checkout-shopper": 3, "ops-admin": 1})
check("inline-list", m["flows"] == ["pay", "cancel-mid-run"])
check("folded-block", m["story"].startswith("Three shoppers") and "\n" not in m["story"])

MODEL = """target: dbos
actor-model: process-parallel
personas:
  checkout-shopper: {weight: 0.6, flows: [pay, browse], citation: "readme quickstart"}
  ops-admin:
    weight: 0.1
    flows: [cancel-mid-run]
    citation: docs/ops
flows:
  pay: {invariants: [charged-exactly-once], citation: "docs: pay"}
events:
  crash-restart: {amplification: 20, citation: recovery}
modules:
  - {name: core, covered-by: [pay]}
  - {name: cli, parked: "no runtime surface"}
"""
m2 = fm.parse(MODEL)
check("nested-map", m2["personas"]["ops-admin"]["weight"] == 0.1)
check("nested-inline", m2["personas"]["checkout-shopper"]["flows"] == ["pay", "browse"])
check("dash-list-of-dicts", m2["modules"][0] == {"name": "core", "covered-by": ["pay"]})
check("quoted-colon", m2["flows"]["pay"]["citation"] == "docs: pay")

# round trip
rt = fm.parse(fm.dump(m2))
check("round-trip", rt == m2, f"{rt!r}")

# load/save with body
with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "s.md")
    fm.save(p, m, "why this scenario\n")
    meta, body = fm.load(p)
    check("save-load-meta", meta == m, f"{meta!r}")
    check("save-load-body", body.strip() == "why this scenario")
    with open(os.path.join(d, "plain.md"), "w") as f:
        f.write("no fence here\n")
    meta2, body2 = fm.load(os.path.join(d, "plain.md"))
    check("unfenced", meta2 == {} and "no fence" in body2)

# loud failures
for bad in ["\tkey: v", "just words no colon", "k: [unterminated"]:
    try:
        fm.parse(bad)
        check(f"loud({bad[:12]!r})", False, "did not raise")
    except ValueError:
        check(f"loud({bad[:12]!r})", True)

print("SELFTEST", "FAIL" if FAILS else "OK")
sys.exit(1 if FAILS else 0)
