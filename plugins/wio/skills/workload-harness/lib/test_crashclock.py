#!/usr/bin/env python3
"""Probe for crashclock.py (calibration probe). Four groups, ALL must pass:

  (1) determinism      — same seed+space => same offsets across processes, x100
  (2) space coverage   — over seeds 1..200 every declared point/style of each space is
                         hit, and no swept range point has >30% mass (non-degenerate)
  (3) selftest hook    — ORACLE_SELFTEST makes the micro-demo oracle fire RED
  (4) end-to-end demo  — spawn a trivial child workload (subprocess appending acked
                         lines with fsync), kill it via a seed-derived clock, restart,
                         verify INVARIANT/VERDICT lines for a survivable (GREEN) case
                         AND a planted-loss selftest (RED)

Run: python3 lib/test_crashclock.py    (exit 0 = all groups pass)
"""

import os
import subprocess
import sys
import tempfile
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import crashclock as cc  # noqa: E402


def _fmt(ok):
    return "PASS" if ok else "FAIL"


# ---------------------------------------------------------------------------
# Group 1 — determinism (cross-process x100)
# ---------------------------------------------------------------------------

_SPACES = {
    "op": cc.op_index("k", 5, 500),
    "lat": cc.latency_window("w", window_ms=2000.0),
    "phase": cc.phase_straddle("p", settle_ms=64000.0),
    "sched": cc.kill_restart_kill("s", cc.latency_window("leg", 8.0), repeat_lo=2, repeat_hi=5),
}


def _child_offsets_prog():
    # Runs in a fresh interpreter; recomputes offsets for seeds 1..100 across all spaces
    # and prints a stable digest. Any process-dependent hashing would diverge here.
    return (
        "import sys, os; sys.path.insert(0, %r); import crashclock as cc\n"
        "spaces = {'op': cc.op_index('k',5,500), 'lat': cc.latency_window('w',2000.0),\n"
        "  'phase': cc.phase_straddle('p',64000.0),\n"
        "  'sched': cc.kill_restart_kill('s', cc.latency_window('leg',8.0), 2, 5)}\n"
        "import json\n"
        "out=[]\n"
        "for seed in range(1,101):\n"
        "  for name in sorted(spaces):\n"
        "    out.append(cc._render_point(cc.offsets(seed, spaces[name])))\n"
        "print(chr(10).join(out))\n"
    ) % HERE


def group1_determinism():
    prog = _child_offsets_prog()
    baseline = None
    runs = 100
    for i in range(runs):
        # PYTHONHASHSEED randomized per child: proves the mapping does NOT use salted hash()
        env = dict(os.environ, PYTHONHASHSEED=str(i * 7 + 1))
        r = subprocess.run([sys.executable, "-c", prog], capture_output=True, text=True, env=env)
        if r.returncode != 0:
            print(f"  child {i} failed: {r.stderr[:300]}")
            return False
        if baseline is None:
            baseline = r.stdout
        elif r.stdout != baseline:
            print(f"  child {i} diverged from baseline (non-deterministic mapping)")
            return False
    # sanity: baseline is non-empty and varies across seeds (not a constant)
    lines = baseline.strip().splitlines()
    ok = len(lines) == 100 * len(_SPACES) and len(set(lines)) > 10
    print(f"  {runs} processes identical; {len(set(lines))} distinct points over 100 seeds")
    return ok


# ---------------------------------------------------------------------------
# Group 2 — space coverage + non-degeneracy over seeds 1..200
# ---------------------------------------------------------------------------


def group2_coverage():
    seeds = range(1, 201)
    ok = True

    # (c) phase straddle: every declared phase hit; none dominates
    phase_space = cc.phase_straddle("p", settle_ms=64000.0)
    phases = Counter(cc.offsets(s, phase_space)["phase"] for s in seeds)
    missing = set(cc.PHASES) - set(phases)
    top_frac = max(phases.values()) / sum(phases.values())
    phase_ok = not missing and top_frac <= 0.45  # 3 styles: ~1/3 each, allow slack
    print(f"  phase: hit={dict(phases)} missing={missing or 'none'} top={top_frac:.2f} {_fmt(phase_ok)}")
    ok = ok and phase_ok

    # (a) op-index: swept range, no single K > 30% mass, and full lo..hi span exercised
    op_space = cc.op_index("k", 10, 60)  # 51 values
    ks = Counter(cc.offsets(s, op_space)["K"] for s in seeds)
    op_top = max(ks.values()) / sum(ks.values())
    span_hit = (max(ks) - min(ks)) >= 0.7 * (60 - 10)
    op_ok = op_top <= 0.30 and span_hit and all(10 <= k <= 60 for k in ks)
    print(f"  op_index: distinct_K={len(ks)} span={min(ks)}..{max(ks)} top_mass={op_top:.2f} {_fmt(op_ok)}")
    ok = ok and op_ok

    # (b) latency-window: log-uniform, no bucket > 30%; both the zero-corner and the
    # far end of the window are reached; sub-ms region populated (log, not linear)
    lat_space = cc.latency_window("w", window_ms=2000.0)
    ts = [cc.offsets(s, lat_space)["T_ms"] for s in seeds]
    zero_hits = sum(1 for t in ts if t == 0.0)
    subms = sum(1 for t in ts if 0.0 < t < 1.0)
    far = sum(1 for t in ts if t > 1000.0)
    # decade buckets over the non-zero mass
    buckets = Counter()
    for t in ts:
        if t == 0.0:
            buckets["zero"] += 1
        else:
            import math
            buckets[int(math.floor(math.log10(t)))] += 1
    lat_top = max(buckets.values()) / len(ts)
    lat_ok = zero_hits > 0 and subms > 0 and far > 0 and lat_top <= 0.30
    print(f"  latency_window: zero={zero_hits} sub_ms={subms} far(>1s)={far} "
          f"buckets={dict(buckets)} top_mass={lat_top:.2f} {_fmt(lat_ok)}")
    ok = ok and lat_ok

    # (d) schedule: repeat count is swept across its whole declared range
    sched_space = cc.kill_restart_kill("s", cc.latency_window("leg", 8.0), repeat_lo=2, repeat_hi=5)
    reps = Counter(cc.offsets(s, sched_space)["repeat"] for s in seeds)
    sched_ok = set(reps) == {2, 3, 4, 5} and max(reps.values()) / sum(reps.values()) <= 0.45
    print(f"  schedule: repeats={dict(sorted(reps.items()))} {_fmt(sched_ok)}")
    ok = ok and sched_ok

    return ok


# ---------------------------------------------------------------------------
# Micro-demo child workload (written to a temp file, spawned as a subprocess)
# ---------------------------------------------------------------------------

_MICRO_WORKLOAD = r'''#!/usr/bin/env python3
"""Trivial child workload: append acked lines to a file with fsync, get SIGKILLed at a
seed-derived op-index clock, restart, verify no acked line was lost.

An 'ack' = the line is fsync'd to disk AND its index recorded in a manifest that is
itself fsync'd. Oracle: every acked line is present after restart (terminal-state /
durability). ORACLE_SELFTEST drops one acked line to force RED.
"""
import os, sys, signal, subprocess, time
sys.path.insert(0, %(here)r)
import crashclock as cc

DATA = os.environ["MICRO_DATA"]
MANIFEST = DATA + ".manifest"
ROLE = sys.argv[1] if len(sys.argv) > 1 else "driver"

def appender():
    # child: append lines forever, fsync each, record acked index in manifest (fsync'd)
    i = 0
    f = open(DATA, "a")
    m = open(MANIFEST, "a")
    while True:
        line = "line-%%08d\n" %% i
        f.write(line); f.flush(); os.fsync(f.fileno())
        m.write("%%d\n" %% i); m.flush(); os.fsync(m.fileno())
        i += 1
        time.sleep(0.002)

if ROLE == "appender":
    appender()
    sys.exit(0)

# driver role: spawn appender, arm an op-index clock, kill, restart-verify
seed = cc.derive_seed()
space = cc.op_index("killops", 20, 120)
pt = cc.offsets(seed, space)
cc.clock_armed("micro", pt)
target_ops = pt["K"]

open(DATA, "w").close(); open(MANIFEST, "w").close()
proc = subprocess.Popen([sys.executable, __file__, "appender"])

# wait until at least target_ops acks are durable, then kill mid-flight
deadline = time.monotonic() + 30
acked = 0
while time.monotonic() < deadline:
    try:
        with open(MANIFEST) as mf:
            acked = sum(1 for _ in mf)
    except FileNotFoundError:
        acked = 0
    if acked >= target_ops:
        break
    time.sleep(0.005)

if acked < target_ops:
    cc.void("appender never reached %%d acks (%%d) — kill point unreached" %% (target_ops, acked))
applied = cc.kill_self_child(proc, mode="sigkill")
proc.wait(timeout=10)

# anti-vacuity floor: enough acked ops before the kill, else the trial proves nothing
with open(MANIFEST) as mf:
    acked_idxs = [int(x) for x in mf.read().split()]
if len(acked_idxs) < 10:
    cc.void("only %%d acked ops before kill — below floor 10" %% len(acked_idxs))

# restart-verify: read the data file back; every acked index must be present
with open(DATA) as df:
    present = set()
    for ln in df:
        ln = ln.strip()
        if ln.startswith("line-"):
            present.add(int(ln[5:]))

if cc.selftest_active():
    victim = acked_idxs[0]
    present.discard(victim)  # plant a loss the oracle must catch
    cc.log("ORACLE_SELFTEST: dropped acked index %%d" %% victim)

missing = [i for i in acked_idxs if i not in present]
if missing:
    cc.red("%%d acked line(s) lost after restart: %%s" %% (len(missing), missing[:10]),
           inv=("acked_survive", "acked-durable-after-kill"))
cc.invariant("acked_survive", "acked-durable-after-kill", True,
             "%%d/%%d acked lines present after SIGKILL+restart (killed via %%s at K=%%d)"
             %% (len(acked_idxs), len(acked_idxs), applied, target_ops))
cc.green("all acked lines durable")
''' % {"here": HERE}


def _run_micro(seed, selftest):
    with tempfile.TemporaryDirectory() as td:
        wl = os.path.join(td, "micro_wl.py")
        with open(wl, "w") as f:
            f.write(_MICRO_WORKLOAD)
        env = dict(os.environ, SEED=str(seed), MICRO_DATA=os.path.join(td, "acked.log"))
        if selftest:
            env["ORACLE_SELFTEST"] = "1"
        else:
            env.pop("ORACLE_SELFTEST", None)
        r = subprocess.run([sys.executable, wl, "driver"], capture_output=True, text=True, env=env)
        return r.returncode, r.stdout


def group3_selftest():
    # Selftest must force RED across several seeds (the planted loss cannot pass).
    seeds_red = 0
    for seed in (1, 2, 3, 5, 8):
        rc, out = _run_micro(seed, selftest=True)
        has_fail = "INVARIANT acked_survive acked-durable-after-kill FAIL" in out
        has_red = "VERDICT: RED" in out
        if rc == 1 and has_fail and has_red:
            seeds_red += 1
        else:
            print(f"  seed {seed}: selftest did NOT force RED (rc={rc})\n{out[-300:]}")
    ok = seeds_red == 5
    print(f"  selftest forced RED on {seeds_red}/5 seeds {_fmt(ok)}")
    return ok


def group4_end_to_end():
    # GREEN case: a survivable kill (no planted loss) must emit PASS + GREEN + a CLOCK line.
    green_ok = 0
    for seed in (1, 2, 3, 7, 11):
        rc, out = _run_micro(seed, selftest=False)
        has_clock = "CLOCK micro armed" in out and "K=" in out
        has_pass = "INVARIANT acked_survive acked-durable-after-kill PASS" in out
        has_green = "VERDICT: GREEN" in out
        # VOID is acceptable (kill point unreached) but for these seeds we expect GREEN
        if rc == 0 and has_clock and has_pass and has_green:
            green_ok += 1
        elif rc == 3:
            print(f"  seed {seed}: VOID (anti-vacuity floor) — acceptable but not counted")
        else:
            print(f"  seed {seed}: unexpected (rc={rc})\n{out[-400:]}")
    # RED case already covered by group 3; assert both directions here for completeness
    rc_r, out_r = _run_micro(1, selftest=True)
    red_ok = rc_r == 1 and "VERDICT: RED" in out_r
    ok = green_ok >= 4 and red_ok
    print(f"  survivable(GREEN)={green_ok}/5  planted-loss(RED)={_fmt(red_ok)} {_fmt(ok)}")
    return ok


def main():
    groups = [
        ("1 determinism (x100 processes)", group1_determinism),
        ("2 space coverage + non-degeneracy", group2_coverage),
        ("3 selftest hook fires RED", group3_selftest),
        ("4 end-to-end micro-demo (green+red)", group4_end_to_end),
    ]
    results = []
    for name, fn in groups:
        print(f"\n=== GROUP {name} ===")
        try:
            ok = fn()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            ok = False
        results.append((name, ok))
    print("\n=== SUMMARY ===")
    all_ok = True
    for name, ok in results:
        print(f"  {_fmt(ok)}  group {name}")
        all_ok = all_ok and ok
    print(f"\n{'ALL GROUPS PASS' if all_ok else 'FAILURE'}")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
