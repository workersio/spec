#!/usr/bin/env python3
"""Bare-runnable selftest for check.py (no pytest)."""
import io
import os
import shutil
import sys
import tempfile
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check  # noqa: E402

FAILS = 0


def ok(name, cond, detail=""):
    global FAILS
    if cond:
        print(f"PASS {name}")
    else:
        FAILS += 1
        print(f"FAIL {name} {detail}")


def run(*argv):
    """Run check.main(argv); return (exit_code, stdout)."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = check.main(list(argv))
    return code, buf.getvalue()


# --------------------------------------------------------------------------- #
# the valid fixture -- built once as a helper, mutated per case
# --------------------------------------------------------------------------- #
MODEL = """---
target: shop
actor-model: process-parallel
personas:
  checkout-shopper: {weight: 0.6, flows: [pay, browse], citation: "readme quickstart"}
  ops-admin: {weight: 0.1, flows: [pay], citation: "docs/ops"}
  api-explorer: {weight: 0.05, flows: []}
  contract-abuser: {weight: 0.05, flows: []}
flows:
  pay:
    invariants: [charged-exactly-once]
    citation: "docs: pay"
    modalities:
      sync: plan
      async: "park: only sync client documented [audited e1]"
      threaded: "park: no threaded usage in docs [audited e1]"
  browse:
    invariants: [listing-consistent]
    citation: "docs: browse"
    modalities:
      sync: plan
      async: "park: only sync client documented [audited e1]"
      threaded: "park: no threaded usage in docs [audited e1]"
events:
  crash-restart: {amplification: 20, citation: recovery}
modules:
  - {name: core, covered-by: [pay, browse]}
  - {name: cli, parked: "no runtime surface [audited e1]"}
surfaces:
  - {name: "shop.pay()", covered-by: [pay]}
  - {name: "shop.browse()", covered-by: [browse]}
  - {name: "shop.admin", parked: "no sim-reachable surface [audited e1]"}
---
usage model prose
"""

FLOWS_PY = '''\
"""flow module for the shop target -- classes first, FLOWS last."""


class PayFlow:
    key = "pay"
    invariants = ("charged-exactly-once",)

    def run(self, ctx):
        pass


class BrowseFlow:
    key = "browse"
    invariants = ("listing-consistent",)

    def run(self, ctx):
        pass


FLOWS = {"pay": PayFlow, "browse": BrowseFlow}
'''

JOURNAL = """## config

target: shop
seed-root: 0
api-floor-share: 0.3
event-min-amp: 10

## log
"""

CANDIDATES = """# Candidates

<!-- emit:begin -->
<!-- emit:end -->

## Backlog

| key | rung | status | note |
| --- | --- | --- | --- |
| cand-a | L1 | idea | one |
| cand-b | L2 | idea | two |
| cand-c | L3 | idea | three |
"""


def scenario(key, *, rung="L0", cast="{checkout-shopper: 1}", flows="[pay]",
             invariants="[charged-exactly-once]", depth=20, status="done",
             result="green", redproof="run-abc", modality="sync", source="usage",
             extra=""):
    return f"""---
key: {key}
rung: {rung}
cast: {cast}
flows: {flows}
invariants: {invariants}
modality: {modality}
source: {source}
depth: {depth}
status: {status}
result: {result}
replay: null
redproof: {redproof}
story: >-
  One sentence a non-engineer can read about {key}.
{extra}---
prose for {key}
"""


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def build_valid(root):
    """A fully-valid small tree: both flows L0-baselined + green, plus the
    misuse/api-floor scenario that ALSO attacks both flows at L2 (a flow
    interaction) while exercising the amplified event -- so every stop gate
    (v0.1.5 six: modality parity, census, api-floor share, event coverage,
    misuse floor, park audit; and the v0.1.6 aim-debt gate: every mapped
    oracle'd flow is attacked past its baseline) is clear and --status prints
    row 1."""
    write(os.path.join(root, "usage-model.md"), MODEL)
    write(os.path.join(root, "flows", "flows_shop.py"), FLOWS_PY)
    write(os.path.join(root, "journal.md"), JOURNAL)
    write(os.path.join(root, "candidates.md"), CANDIDATES)
    write(os.path.join(root, "scenarios", "pay-basic.md"),
          scenario("pay-basic", flows="[pay]", invariants="[charged-exactly-once]",
                   redproof="run-pay"))
    write(os.path.join(root, "scenarios", "browse-basic.md"),
          scenario("browse-basic", flows="[browse]", invariants="[listing-consistent]",
                   redproof="run-browse"))
    write(os.path.join(root, "scenarios", "abuse-pay.md"),
          scenario("abuse-pay", rung="L2", cast="{contract-abuser: 1}",
                   flows="[pay, browse]",
                   invariants="[charged-exactly-once, listing-consistent]",
                   redproof="run-abuse", source="api-floor",
                   extra="event: {key: crash-restart, at: crashclock}\n"))
    return root


def fresh(builder=build_valid):
    d = tempfile.mkdtemp(prefix="wio-check-")
    builder(d)
    return d


# --------------------------------------------------------------------------- #
# valid tree passes
# --------------------------------------------------------------------------- #
d = fresh()
code, out = run("--root", d)
ok("valid-clean-exit0", code == 0, out)
ok("valid-clean-summary", "CHECK OK (3 scenarios, 2 flows)" in out, out)
ok("valid-no-gfail", "FAIL" not in out, out)
shutil.rmtree(d)


def expect_gfail(name, gnum, mutate, extra_check=None):
    d = fresh()
    mutate(d)
    code, out = run("--root", d)
    tag = f"G{gnum} FAIL"
    ok(f"{name}-exit2", code == 2, out)
    ok(f"{name}-{tag}", tag in out, out)
    if extra_check:
        extra_check(out)
    shutil.rmtree(d)


# G1: scenario references a flow not in the model
expect_gfail("g1", 1, lambda d: write(
    os.path.join(d, "scenarios", "pay-basic.md"),
    scenario("pay-basic", flows="[ghost]", invariants="[charged-exactly-once]",
             redproof="run-pay")))

# G2: FLOWS registry not a bijection with the model (extra flow)
expect_gfail("g2-extra", 2, lambda d: write(
    os.path.join(d, "flows", "flows_shop.py"),
    FLOWS_PY.replace(
        'FLOWS = {"pay": PayFlow, "browse": BrowseFlow}',
        'class GhostFlow:\n    key = "ghost"\n\n\n'
        'FLOWS = {"pay": PayFlow, "browse": BrowseFlow, "ghost": GhostFlow}')))

# G2: FLOWS dict key disagrees with the class key attr
expect_gfail("g2-keymismatch", 2, lambda d: write(
    os.path.join(d, "flows", "flows_shop.py"),
    FLOWS_PY.replace('"pay": PayFlow', '"paye": PayFlow')))

# G3: scenario invariant not provided by any of its flows
expect_gfail("g3", 3, lambda d: write(
    os.path.join(d, "scenarios", "pay-basic.md"),
    scenario("pay-basic", flows="[pay]", invariants="[charged-exactly-once, never-declared]",
             redproof="run-pay")))

# G4: ready scenario missing required fields (empty cast)
expect_gfail("g4", 4, lambda d: write(
    os.path.join(d, "scenarios", "pay-basic.md"),
    scenario("pay-basic", status="ready", result="null", redproof="null",
             cast="{}", flows="[pay]", invariants="[charged-exactly-once]")))

# G5 (HARD): done + green + redproof null fails
expect_gfail("g5", 5, lambda d: write(
    os.path.join(d, "scenarios", "pay-basic.md"),
    scenario("pay-basic", flows="[pay]", invariants="[charged-exactly-once]",
             redproof="null")))

# G5: done + green + concrete redproof passes
d = fresh()
write(os.path.join(d, "scenarios", "pay-basic.md"),
      scenario("pay-basic", flows="[pay]", invariants="[charged-exactly-once]",
               redproof="draft-run-991"))
code, out = run("--root", d)
ok("g5-redproof-passes", code == 0 and "G5 FAIL" not in out, out)
shutil.rmtree(d)

# G6: persona citation missing
expect_gfail("g6", 6, lambda d: write(
    os.path.join(d, "usage-model.md"),
    MODEL.replace(', citation: "docs/ops"', "")))

# G7: duplicate key across scenarios
expect_gfail("g7-dup", 7, lambda d: write(
    os.path.join(d, "scenarios", "dup.md"),
    scenario("pay-basic", flows="[pay]", invariants="[charged-exactly-once]",
             redproof="run-x")))

# G7: finding references a nonexistent scenario key
expect_gfail("g7-orphan-finding", 7, lambda d: write(
    os.path.join(d, "findings", "f1.md"),
    """---
key: finding-1
scenario: does-not-exist
---
finding prose
"""))

# G8: module entry with neither covered-by nor parked
expect_gfail("g8", 8, lambda d: write(
    os.path.join(d, "usage-model.md"),
    MODEL.replace('  - {name: cli, parked: "no runtime surface [audited e1]"}',
                  "  - {name: cli}")))

# G10: flow with no modalities declaration
expect_gfail("g10-flow-modalities", 10, lambda d: write(
    os.path.join(d, "usage-model.md"),
    MODEL.replace("""    modalities:
      sync: plan
      async: "park: only sync client documented [audited e1]"
      threaded: "park: no threaded usage in docs [audited e1]"
events:""", "events:")))

# G10: done scenario with an unknown modality value
expect_gfail("g10-scenario-modality", 10, lambda d: write(
    os.path.join(d, "scenarios", "pay-basic.md"),
    scenario("pay-basic", flows="[pay]", invariants="[charged-exactly-once]",
             redproof="run-pay", modality="psychic")))

# G10: done scenario with an unknown source value
expect_gfail("g10-scenario-source", 10, lambda d: write(
    os.path.join(d, "scenarios", "pay-basic.md"),
    scenario("pay-basic", flows="[pay]", invariants="[charged-exactly-once]",
             redproof="run-pay", source="vibes")))

# G11: surface entry with neither covered-by nor parked
expect_gfail("g11", 11, lambda d: write(
    os.path.join(d, "usage-model.md"),
    MODEL.replace('  - {name: "shop.admin", parked: "no sim-reachable surface [audited e1]"}',
                  '  - {name: "shop.admin"}')))

# G9: unparseable scenario frontmatter
expect_gfail("g9-parse", 9, lambda d: write(
    os.path.join(d, "scenarios", "broken.md"),
    "---\n\tkey: bad-indent\n---\nbody\n"))

# G9: journal.md without a ## config section
expect_gfail("g9-journal", 9, lambda d: write(
    os.path.join(d, "journal.md"), "## log\nno config here\n"))


# --------------------------------------------------------------------------- #
# --status rows
# --------------------------------------------------------------------------- #
# Row 1: the complete valid tree — all stop gates clear
d = fresh()
code, out = run("--root", d, "--status")
ok("status-row1", code == 0 and "STATUS row=1" in out, out)
ok("status-row1-no-blockers", "STOP-BLOCKERS (0): none" in out, out)
shutil.rmtree(d)

# Blocker: misuse floor — removing the contract-abuser scenario blocks stop
d = fresh()
os.remove(os.path.join(d, "scenarios", "abuse-pay.md"))
code, out = run("--root", d, "--status")
ok("blocker-misuse-no-row1", "STATUS row=1" not in out, out)
ok("blocker-misuse-named", "misuse:" in out, out)
ok("blocker-event-named", "event: 'crash-restart'" in out, out)
ok("blocker-apifloor-named", "api-floor:" in out, out)
shutil.rmtree(d)

# Blocker: modality parity — flipping a planned modality's done scenario away
d = fresh()
write(os.path.join(d, "usage-model.md"),
      MODEL.replace('''  browse:
    invariants: [listing-consistent]
    citation: "docs: browse"
    modalities:
      sync: plan
      async: "park: only sync client documented [audited e1]"''',
                    '''  browse:
    invariants: [listing-consistent]
    citation: "docs: browse"
    modalities:
      sync: plan
      async: plan'''))
code, out = run("--root", d, "--status")
ok("blocker-modality-no-row1", "STATUS row=1" not in out, out)
ok("blocker-modality-named", "modality: flow 'browse' async planned" in out, out)
shutil.rmtree(d)

# Blocker: park audit — a park without the [audited eN] tag blocks stop
d = fresh()
write(os.path.join(d, "usage-model.md"),
      MODEL.replace('parked: "no runtime surface [audited e1]"',
                    'parked: "no runtime surface"'))
code, out = run("--root", d, "--status")
ok("blocker-parkaudit-no-row1", "STATUS row=1" not in out, out)
ok("blocker-parkaudit-named", "park-audit:" in out, out)
shutil.rmtree(d)

# Blocker: census — removing surfaces: entirely blocks stop
d = fresh()
model_nosurf = MODEL[:MODEL.index("surfaces:")] + "---\nusage model prose\n"
write(os.path.join(d, "usage-model.md"), model_nosurf)
code, out = run("--root", d, "--status")
ok("blocker-census-no-row1", "STATUS row=1" not in out, out)
ok("blocker-census-named", "census:" in out, out)
shutil.rmtree(d)

# Blocker: aim-debt — a mapped, oracle'd flow baselined green but never
# attacked. Demoting the L2 attacker back to an L0 baseline leaves pay and
# browse with only green controls, so the gate owes an attack on each.
d = fresh()
write(os.path.join(d, "scenarios", "abuse-pay.md"),
      scenario("abuse-pay", rung="L0", cast="{contract-abuser: 1}",
               flows="[pay]", invariants="[charged-exactly-once]",
               redproof="run-abuse", source="api-floor",
               extra="event: {key: crash-restart, at: crashclock}\n"))
code, out = run("--root", d, "--status")
ok("blocker-aimdebt-no-row1", "STATUS row=1" not in out, out)
ok("blocker-aimdebt-named", "aim-debt:" in out, out)
shutil.rmtree(d)

# Blocker: anti-monoculture breadth floor — one cluster deepened (2 attackers
# on pay) while breadth < K distinct flows attacked (browse never attacked).
# Replacing the single both-flows L2 with two pay-only L1 attackers collapses
# the whole attacking budget onto one cluster.
d = fresh()
os.remove(os.path.join(d, "scenarios", "abuse-pay.md"))
write(os.path.join(d, "scenarios", "abuse-pay-1.md"),
      scenario("abuse-pay-1", rung="L1", cast="{contract-abuser: 1}",
               flows="[pay]", invariants="[charged-exactly-once]",
               redproof="run-abuse1", source="api-floor",
               extra="event: {key: crash-restart, at: crashclock}\n"))
write(os.path.join(d, "scenarios", "abuse-pay-2.md"),
      scenario("abuse-pay-2", rung="L1", cast="{contract-abuser: 1}",
               flows="[pay]", invariants="[charged-exactly-once]",
               redproof="run-abuse2", source="api-floor"))
code, out = run("--root", d, "--status")
ok("blocker-antimono-no-row1", "STATUS row=1" not in out, out)
ok("blocker-antimono-named", "anti-monoculture: flow 'pay' deepened" in out, out)
shutil.rmtree(d)

# Blocker: per-cluster episode budget cap — even at full breadth, one flow
# cannot absorb more than the cap. Setting cluster-attack-cap: 1 in journal
# config means the L2 that attacks both flows keeps each at exactly 1 (clear),
# so we add a 2nd pay attacker to push pay over the cap while browse stays at 1.
d = fresh()
write(os.path.join(d, "journal.md"),
      JOURNAL.replace("event-min-amp: 10",
                      "event-min-amp: 10\ncluster-attack-cap: 1"))
write(os.path.join(d, "scenarios", "deepen-pay.md"),
      scenario("deepen-pay", rung="L1", cast="{contract-abuser: 1}",
               flows="[pay]", invariants="[charged-exactly-once]",
               redproof="run-deepen", source="api-floor"))
code, out = run("--root", d, "--status")
ok("blocker-clusterbudget-named", "cluster-budget: flow 'pay'" in out, out)
shutil.rmtree(d)

# Row 5: a ready scenario (backlog >=5 rows, no refresh trigger)
d = fresh()
write(os.path.join(d, "scenarios", "browse-basic.md"),
      scenario("browse-basic", status="ready", result="null", redproof="null",
               flows="[browse]", invariants="[listing-consistent]"))
code, out = run("--root", d, "--status")
ok("status-row5", "STATUS row=5" in out, out)
shutil.rmtree(d)

# Row 3: an un-crystallized finding outranks a ready scenario (order check)
d = fresh()
write(os.path.join(d, "scenarios", "browse-basic.md"),
      scenario("browse-basic", status="ready", result="null", redproof="null",
               flows="[browse]", invariants="[listing-consistent]"))
write(os.path.join(d, "scenarios", "pay-basic.md"),
      scenario("pay-basic", status="done", result="finding", redproof="null",
               flows="[pay]", invariants="[charged-exactly-once]"))
code, out = run("--root", d, "--status")
ok("status-row3-outranks-row5", "STATUS row=3" in out, out)
shutil.rmtree(d)


# --------------------------------------------------------------------------- #
# --emit idempotency and byte preservation outside the markers
# --------------------------------------------------------------------------- #
d = fresh()
cpath = os.path.join(d, "candidates.md")
orig = open(cpath, encoding="utf-8").read()

run("--root", d, "--emit")
after1 = open(cpath, encoding="utf-8").read()
run("--root", d, "--emit")
after2 = open(cpath, encoding="utf-8").read()
ok("emit-idempotent", after1 == after2, "emit not idempotent")


def outside_markers(text):
    bi = text.find(check.EMIT_BEGIN)
    ei = text.find(check.EMIT_END)
    return text[: bi + len(check.EMIT_BEGIN)], text[ei:]


ok("emit-preserves-pre", outside_markers(orig)[0] == outside_markers(after1)[0],
   "pre-marker bytes changed")
ok("emit-preserves-post", outside_markers(orig)[1] == outside_markers(after1)[1],
   "post-marker bytes changed")
ok("emit-filled-block", "status: planned=" in after1 and "| pay |" in after1, after1)
shutil.rmtree(d)

# --emit creates candidates.md with a skeleton when missing
d = fresh()
os.remove(os.path.join(d, "candidates.md"))
run("--root", d, "--emit")
ok("emit-creates-file", os.path.exists(os.path.join(d, "candidates.md")))
shutil.rmtree(d)


print("SELFTEST", "FAIL" if FAILS else "OK")
sys.exit(1 if FAILS else 0)
