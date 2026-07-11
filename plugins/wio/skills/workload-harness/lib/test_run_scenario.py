#!/usr/bin/env python3
"""Bare-runnable smoke test for run_scenario.py (no pytest).

Builds a throwaway ``.workers/`` tree with a stub flows module (its own tiny SUT +
one flow + EVENTS + FLOWS), then drives run_scenario.py via subprocess so exit codes
are real. The stub records into ctx.ledger through duck-typed, hasattr-guarded calls,
so this test does not depend on the concurrently-written oracle modules -- except the
optional --redproof assertion, which is skipped with a SKIP line if personaledger.py
is not present yet.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

LIB = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.join(LIB, "run_scenario.py")

FAILS = 0


def check(name, cond, detail=""):
    global FAILS
    if cond:
        print(f"PASS {name}")
    else:
        FAILS += 1
        print(f"FAIL {name} {detail}")


STUB_FLOWS = '''\
import os
import time


class StubSUT:
    def __init__(self, meta, seed):
        self.store = {}

    def write(self, ctx, key, value, mode):
        # ack: the product told this actor the write succeeded
        if hasattr(ctx, "ledger") and hasattr(ctx.ledger, "acked"):
            ctx.ledger.acked("write", key, value)
        # 'red' mode: acked but the effect is silently dropped (a real lost write)
        if mode != "red":
            self.store[key] = value
        present = key in self.store
        if hasattr(ctx, "ledger") and hasattr(ctx.ledger, "observe"):
            ctx.ledger.observe("write", key, value=self.store.get(key), present=present)

    def stop(self):
        pass


class ActFlow:
    key = "act"
    invariants = ("thing-durable",)
    documented = {}
    bounds = {}

    def run(self, ctx):
        mode = os.environ.get("WIO_STUB_MODE", "healthy")
        if mode == "hang":
            ctx.step("begin")
            time.sleep(999)
            return
        ctx.step("begin")
        if mode == "void":
            # record nothing in any oracle -> the run is VOID, not GREEN
            ctx.step("end")
            return
        ctx.sut.write(ctx, ctx.actor_id + ":k", 1, mode)
        if hasattr(ctx, "errors") and ctx.errors is not None:
            try:
                with ctx.errors.expect("act"):
                    pass
            except Exception:
                pass
        ctx.step("end")


def make_sut(meta, seed):
    return StubSUT(meta, seed)


FLOWS = {"act": ActFlow}
EVENTS = {}
'''

USAGE_MODEL = """---
target: stub
actor-model: thread-parallel
personas:
  worker: {weight: 1.0, flows: [act], citation: "x"}
flows:
  act: {invariants: [thing-durable], citation: "x"}
---
usage model body
"""

SCENARIO_1 = """---
key: t
rung: L0
cast: {worker: 1}
flows: [act]
invariants: [thing-durable]
depth: 5
status: planned
---
one worker writes one thing.
"""

SCENARIO_MULTI = """---
key: m
rung: L1
cast: {worker: 2}
flows: [act]
invariants: [thing-durable]
depth: 5
status: planned
---
two workers write concurrently.
"""


def build_tree(base: Path, with_flows: bool = True) -> Path:
    workers = base / ".workers"
    (workers / "scenarios").mkdir(parents=True, exist_ok=True)
    (workers / "flows").mkdir(parents=True, exist_ok=True)
    (workers / "usage-model.md").write_text(USAGE_MODEL)
    (workers / "scenarios" / "t.md").write_text(SCENARIO_1)
    (workers / "scenarios" / "m.md").write_text(SCENARIO_MULTI)
    if with_flows:
        (workers / "flows" / "flows_stub.py").write_text(STUB_FLOWS)
    return workers


def run(scenario: Path, args=(), env_over=None):
    env = dict(os.environ)
    env.setdefault("WIO_SEED", "1")
    if env_over:
        env.update(env_over)
    proc = subprocess.run(
        [sys.executable, RUNNER, str(scenario), *args],
        capture_output=True, text=True, env=env, timeout=60,
    )
    return proc.returncode, proc.stdout, proc.stderr


with tempfile.TemporaryDirectory() as d:
    base = Path(d)
    workers = build_tree(base)
    t = workers / "scenarios" / "t.md"
    m = workers / "scenarios" / "m.md"

    # 1) SEED + PLAN lines, GREEN on a healthy stub
    rc, out, err = run(t, env_over={"WIO_STUB_MODE": "healthy"})
    check("seed-line", "SEED 1" in out, out)
    check("plan-line", "\nPLAN seed=1 " in ("\n" + out), out)
    check("green-verdict", rc == 0 and "VERDICT GREEN" in out, f"rc={rc}\n{out}\n{err}")

    # 2) --list-plan exits 0 and stops before any verdict
    rc, out, err = run(t, args=("--list-plan",), env_over={"WIO_STUB_MODE": "healthy"})
    check("list-plan-exit0", rc == 0, f"rc={rc}\n{out}")
    check("list-plan-no-verdict", "VERDICT" not in out and "PLAN seed=" in out, out)

    # 3) RED when the stub plants a real acked-then-observed-absent violation
    rc, out, err = run(t, env_over={"WIO_STUB_MODE": "red"})
    check("red-verdict", rc == 1 and "VERDICT RED" in out, f"rc={rc}\n{out}\n{err}")

    # 4) VOID when the flow records nothing
    rc, out, err = run(t, env_over={"WIO_STUB_MODE": "void"})
    check("void-verdict", rc == 3 and "VERDICT VOID" in out, f"rc={rc}\n{out}\n{err}")

    # 5) exit 44 setup-block when the flows module is missing
    with tempfile.TemporaryDirectory() as d2:
        broken = build_tree(Path(d2), with_flows=False)
        rc, out, err = run(broken / "scenarios" / "t.md", env_over={"WIO_STUB_MODE": "healthy"})
        check("setup-block-exit44", rc == 44, f"rc={rc}\n{out}\n{err}")
        check("setup-block-msg", "setup-block:" in err, err)

    # 6) watchdog converts a hang into FAIL exit 1
    rc, out, err = run(t, env_over={"WIO_STUB_MODE": "hang", "WIO_WATCHDOG_S": "2"})
    check("watchdog-exit1", rc == 1, f"rc={rc}\n{out}\n{err}")
    check("watchdog-line", "liveness_watchdog liveness FAIL" in out, out)

    # 7) multi-actor GREEN drives interleave's scheduler (SCHEDULE trace line)
    rc, out, err = run(m, env_over={"WIO_STUB_MODE": "healthy"})
    check("multi-green", rc == 0 and "VERDICT GREEN" in out, f"rc={rc}\n{out}\n{err}")
    check("multi-schedule-line", "SCHEDULE " in out, out)

    # 8) --redproof exits 0 with ORACLE_SELFTEST PASS on the healthy stub
    if os.path.exists(os.path.join(LIB, "personaledger.py")):
        rc, out, err = run(t, args=("--redproof",), env_over={"WIO_STUB_MODE": "healthy"})
        check("redproof-pass", rc == 0 and "ORACLE_SELFTEST PASS" in out,
              f"rc={rc}\n{out}\n{err}")
    else:
        print("SKIP redproof-pass (personaledger.py not present yet)")

print("SELFTEST", "FAIL" if FAILS else "OK")
sys.exit(1 if FAILS else 0)
