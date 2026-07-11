#!/usr/bin/env python3
"""Probe for durawatch.py (calibration probe). Five groups, ALL must pass, run entirely
locally (no cloud):

  (1) determinism/hashing — payload_hash is a pure function of payload bytes across
      processes (PYTHONHASHSEED randomized); manifest round-trips JSON byte-identically.
  (2) selftest fires RED  — ORACLE_SELFTEST plants an erasure; run_ladder goes RED with the
      durability_watch_<rung> FAIL line.
  (3) restart-tolerance   — a watcher subprocess is SIGKILLed mid-ladder; a fresh process
      resume_or_start()s the persisted manifest and completes the watch on the original
      clock (rungs already done are skipped, no rung re-slept).
  (4) flap detection      — an effect that disappears at one rung and returns at the next
      emits a NEARMISS but the final verdict is GREEN (a flap is not a hard loss).
  (5) end-to-end micro    — a toy in-memory store: durable-across-ladder GREEN, and a
      planted delete-after-delay RED (the #627 shape, in miniature, offline).

Run: python3 lib/test_durawatch.py    (exit 0 = all groups pass)
"""

import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import durawatch as dw  # noqa: E402


def _fmt(ok):
    return "PASS" if ok else "FAIL"


# ---------------------------------------------------------------------------
# Group 1 — determinism / hashing correctness across processes
# ---------------------------------------------------------------------------

def _child_hash_prog():
    # Fresh interpreter: hash a fixed set of payloads (incl. key-reordered dicts) and a
    # manifest round-trip; print a digest. Salted hash() would diverge here.
    return (
        "import sys; sys.path.insert(0, %r); import durawatch as dw\n"
        "payloads = [b'raw-bytes', 'a string', {'b':2,'a':1,'c':[3,2,1]},\n"
        "  {'a':1,'b':2,'c':[3,2,1]}, 42, [1,2,{'x':'y'}], 'unicode-\\u00e9']\n"
        "out = [dw.payload_hash(p) for p in payloads]\n"
        "m = dw.WatchState(ladder=[0.0,30.0,75.0], void_floor=2)\n"
        "for i,p in enumerate(payloads[:4]):\n"
        "  m.effects.append(dw.Effect(eid='e%%d'%%i, query={'k':i}, phash=dw.payload_hash(p), acked_at=1.0))\n"
        "js = m.to_json(); rt = dw.WatchState.from_json(js).to_json()\n"
        "out.append('roundtrip=%%s' %% (js==rt))\n"
        "print('|'.join(out))\n"
    ) % HERE


def group1_determinism():
    prog = _child_hash_prog()
    baseline = None
    runs = 50
    for i in range(runs):
        env = dict(os.environ, PYTHONHASHSEED=str(i * 13 + 1))
        r = subprocess.run([sys.executable, "-c", prog], capture_output=True, text=True, env=env)
        if r.returncode != 0:
            print(f"  child {i} failed: {r.stderr[:300]}")
            return False
        if baseline is None:
            baseline = r.stdout
        elif r.stdout != baseline:
            print(f"  child {i} diverged (non-deterministic hashing)")
            return False
    fields = baseline.strip().split("|")
    # key-reordered dicts (index 2 and 3) must collide; roundtrip must be True
    reorder_ok = fields[2] == fields[3]
    roundtrip_ok = fields[-1] == "roundtrip=True"
    all_distinct = len(set(fields[:2] + fields[4:-1])) == len(fields[:2] + fields[4:-1])
    ok = reorder_ok and roundtrip_ok and all_distinct
    print(f"  {runs} processes identical; key-reorder collision={reorder_ok} "
          f"manifest_roundtrip={roundtrip_ok} distinct_others={all_distinct}")
    return ok


# ---------------------------------------------------------------------------
# Toy in-memory store + a workload observe() over it (shared by groups 2,4,5)
# ---------------------------------------------------------------------------

class ToyStore:
    """A minimal key->bytes store standing in for a product. ``get`` returns None when a
    key is absent (unobservable). Scripts can plant an erasure or a flap at a given tick."""

    def __init__(self):
        self.data = {}

    def put(self, k, v):
        self.data[k] = v

    def get(self, k):
        return self.data.get(k)

    def delete(self, k):
        self.data.pop(k, None)


# ---------------------------------------------------------------------------
# Group 2 — selftest fires RED
# ---------------------------------------------------------------------------

def group2_selftest():
    reds = 0
    trials = 5
    for t in range(trials):
        with tempfile.TemporaryDirectory() as td:
            store = ToyStore()
            path = os.path.join(td, "dw.json")
            m = dw.Manifest.start(f"selftest{t}", path, ladder=[0.0], void_floor=1)
            for i in range(3):
                k = f"k{i}"
                store.put(k, f"v{i}".encode())
                m.record(k, {"key": k}, store.get(k))
            observe = lambda eff: store.get(eff.query["key"])
            # Run in a child so sys.exit(1) is captured as an exit code.
            rc, out = _run_ladder_child(td, path, f"selftest{t}", selftest=True)
            if rc == 1 and "durability_watch_t0 acked-effect-durable FAIL" in out and "VERDICT: RED" in out:
                reds += 1
            else:
                print(f"  trial {t}: selftest did NOT force RED (rc={rc})\n{out[-300:]}")
    ok = reds == trials
    print(f"  selftest forced RED on {reds}/{trials} trials {_fmt(ok)}")
    return ok


# A tiny driver script run as a subprocess so exit codes / restarts are real.
_LADDER_DRIVER = r'''
import os, sys, json
sys.path.insert(0, %(here)r)
import durawatch as dw

TD = os.environ["DW_TD"]
PATH = os.environ["DW_PATH"]
CASE = os.environ["DW_CASE"]
STORE = os.path.join(TD, "store.json")

def load_store():
    try:
        with open(STORE) as f: return json.load(f)
    except FileNotFoundError:
        return {}

def observe(eff):
    d = load_store()
    v = d.get(eff.query["key"])
    return v.encode() if isinstance(v, str) else v

m = dw.Manifest.resume_or_start(CASE, PATH)
# zero real sleeps in the probe: collapse the ladder time
m.run_ladder(observe, sleep=lambda s: None)
'''  % {"here": HERE}


def _write_store(td, mapping):
    import json
    with open(os.path.join(td, "store.json"), "w") as f:
        json.dump(mapping, f)


def _run_ladder_child(td, path, case, selftest=False, extra_env=None):
    with tempfile.NamedTemporaryFile("w", suffix=".py", dir=td, delete=False) as f:
        f.write(_LADDER_DRIVER)
        driver = f.name
    env = dict(os.environ, DW_TD=td, DW_PATH=path, DW_CASE=case, PYTHONHASHSEED="0")
    if selftest:
        env["ORACLE_SELFTEST"] = "1"
    else:
        env.pop("ORACLE_SELFTEST", None)
    if extra_env:
        env.update(extra_env)
    r = subprocess.run([sys.executable, driver], capture_output=True, text=True, env=env)
    return r.returncode, r.stdout + r.stderr


# ---------------------------------------------------------------------------
# Group 3 — restart-tolerance: kill mid-ladder, resume, complete
# ---------------------------------------------------------------------------

# A driver that stalls in the middle of the ladder so the parent can SIGKILL it, then a
# second run resumes. We simulate a real (non-zero) ladder and a mid-ladder stall via a
# sentinel file; the resume run uses collapsed sleeps to finish fast.
_RESTART_DRIVER = r'''
import os, sys, json, time
sys.path.insert(0, %(here)r)
import durawatch as dw

TD = os.environ["DW_TD"]
PATH = os.environ["DW_PATH"]
CASE = os.environ["DW_CASE"]
MODE = os.environ["DW_MODE"]   # "first" (dies mid-ladder) or "resume"
STORE = os.path.join(TD, "store.json")

def observe(eff):
    with open(STORE) as f: d = json.load(f)
    v = d.get(eff.query["key"])
    return v.encode() if isinstance(v, str) else v

if MODE == "first":
    # Fresh manifest, record 3 effects, then start a ladder whose rung-1 sleep hangs long
    # enough for the parent to kill us AFTER rung-0 was checked and persisted.
    m = dw.Manifest.start(CASE, PATH, ladder=[0.0, 5.0, 10.0], void_floor=1)
    with open(STORE) as f: d = json.load(f)
    for k in d:
        m.record(k, {"key": k}, d[k].encode())
    open(os.path.join(TD, "ready"), "w").close()
    def slow_sleep(s):
        # touch a marker AFTER rung-0 is done (done_rungs persisted), then hang so we die
        # inside the rung-1 wait, with rung-0 already checkpointed to disk.
        open(os.path.join(TD, "rung0_done"), "w").close()
        time.sleep(600)   # parent SIGKILLs us here
    m.run_ladder(observe, sleep=slow_sleep)
else:  # resume
    m = dw.Manifest.resume_or_start(CASE, PATH)
    # assert we actually reloaded state (t0 pinned, rung 0 already done)
    assert m.state.t0 is not None, "resume lost t0"
    assert 0 in m.state.done_rungs, "resume lost rung-0 progress"
    assert m.effect_count() == 3, "resume lost effects"
    m.run_ladder(observe, sleep=lambda s: None)  # collapse remaining ladder
'''  % {"here": HERE}


def group3_restart():
    with tempfile.TemporaryDirectory() as td:
        _write_store(td, {"k0": "v0", "k1": "v1", "k2": "v2"})
        path = os.path.join(td, "dw.json")
        with tempfile.NamedTemporaryFile("w", suffix=".py", dir=td, delete=False) as f:
            f.write(_RESTART_DRIVER)
            driver = f.name

        # Phase 1: launch, wait until it has checkpointed rung-0, then SIGKILL it.
        env1 = dict(os.environ, DW_TD=td, DW_PATH=path, DW_CASE="restart",
                    DW_MODE="first", PYTHONHASHSEED="0")
        p = subprocess.Popen([sys.executable, driver], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, env=env1)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if os.path.exists(os.path.join(td, "rung0_done")):
                break
            if p.poll() is not None:
                break
            time.sleep(0.02)
        import signal
        killed = False
        if p.poll() is None:
            p.send_signal(signal.SIGKILL)
            killed = True
        p.wait(timeout=10)

        # manifest must exist on disk with rung-0 done (survived the kill)
        if not os.path.exists(path):
            print("  manifest not persisted before kill")
            return False
        with open(path) as f:
            import json
            st = json.load(f)
        pre_ok = 0 in st.get("done_rungs", []) and len(st.get("effects", [])) == 3 \
                 and st.get("t0") is not None

        # Phase 2: resume in a fresh process; must complete GREEN with rungs 1,2.
        env2 = dict(os.environ, DW_TD=td, DW_PATH=path, DW_CASE="restart",
                    DW_MODE="resume", PYTHONHASHSEED="0")
        r = subprocess.run([sys.executable, driver], capture_output=True, text=True, env=env2)
        resume_out = r.stdout + r.stderr
        resumed_green = r.returncode == 0 and "VERDICT: GREEN" in resume_out
        # the resume must NOT re-check rung t0 (already done) but must check t5s/t10s
        rechecked_t0 = "rung t0 observed" in resume_out
        did_later = "rung t5s observed" in resume_out and "rung t10s observed" in resume_out
        ok = killed and pre_ok and resumed_green and not rechecked_t0 and did_later
        print(f"  killed_mid_ladder={killed} manifest_survived(rung0+3eff+t0)={pre_ok} "
              f"resume_green={resumed_green} skipped_done_rung={not rechecked_t0} "
              f"ran_later_rungs={did_later} {_fmt(ok)}")
        return ok


# ---------------------------------------------------------------------------
# Group 4 — flap detection: NEARMISS emitted, verdict still GREEN
# ---------------------------------------------------------------------------

_FLAP_DRIVER = r'''
import os, sys, json
sys.path.insert(0, %(here)r)
import durawatch as dw

TD = os.environ["DW_TD"]; PATH = os.environ["DW_PATH"]; CASE = os.environ["DW_CASE"]
# tick file: which rung we're on, so observe() can hide an effect on rung 1 only
TICK = os.path.join(TD, "tick")

def observe(eff):
    # effect "flapper" is invisible on the 2nd rung (index 1) but present otherwise
    n = int(open(TICK).read()) if os.path.exists(TICK) else 0
    with open(os.path.join(TD, "store.json")) as f: d = json.load(f)
    if eff.query["key"] == "flapper" and n == 1:
        return None
    v = d.get(eff.query["key"])
    return v.encode() if isinstance(v, str) else v

m = dw.Manifest.start(CASE, PATH, ladder=[0.0, 30.0, 75.0], void_floor=1)
with open(os.path.join(TD, "store.json")) as f: d = json.load(f)
for k in d:
    m.record(k, {"key": k}, d[k].encode())

# advance the tick on each sleep so observe() sees rung index via the tick file
state = {"i": 0}
def tick_sleep(s):
    state["i"] += 1
    open(TICK, "w").write(str(state["i"]))
m.run_ladder(observe, sleep=tick_sleep)
'''  % {"here": HERE}


def group4_flap():
    with tempfile.TemporaryDirectory() as td:
        _write_store(td, {"stable": "s", "flapper": "f"})
        path = os.path.join(td, "dw.json")
        with tempfile.NamedTemporaryFile("w", suffix=".py", dir=td, delete=False) as f:
            f.write(_FLAP_DRIVER)
            driver = f.name
        env = dict(os.environ, DW_TD=td, DW_PATH=path, DW_CASE="flap", PYTHONHASHSEED="0")
        env.pop("ORACLE_SELFTEST", None)
        r = subprocess.run([sys.executable, driver], capture_output=True, text=True, env=env)
        out = r.stdout + r.stderr
        has_nearmiss = "flap effect=flapper" in out
        is_green = r.returncode == 0 and "VERDICT: GREEN" in out
        no_fail = "acked-effect-durable FAIL" not in out
        ok = has_nearmiss and is_green and no_fail
        print(f"  nearmiss_emitted={has_nearmiss} verdict_green={is_green} "
              f"no_hard_fail={no_fail} {_fmt(ok)}")
        if not ok:
            print(out[-500:])
        return ok


# ---------------------------------------------------------------------------
# Group 5 — end-to-end micro demo: durable GREEN + planted delete-after-delay RED
# ---------------------------------------------------------------------------

_E2E_DRIVER = r'''
import os, sys, json
sys.path.insert(0, %(here)r)
import durawatch as dw

TD = os.environ["DW_TD"]; PATH = os.environ["DW_PATH"]; CASE = os.environ["DW_CASE"]
FAULT = os.environ.get("DW_FAULT", "none")   # "none" | "delete_after_delay"
TICK = os.path.join(TD, "tick")

def observe(eff):
    n = int(open(TICK).read()) if os.path.exists(TICK) else 0
    with open(os.path.join(TD, "store.json")) as f: d = json.load(f)
    # #627 shape: the acked PUT is present at t0 but ERASED after a delay (rung >= 2)
    if FAULT == "delete_after_delay" and eff.query["key"] == "doomed" and n >= 2:
        return None
    v = d.get(eff.query["key"])
    return v.encode() if isinstance(v, str) else v

m = dw.Manifest.start(CASE, PATH, ladder=[0.0, 30.0, 75.0], void_floor=1)
with open(os.path.join(TD, "store.json")) as f: d = json.load(f)
for k in d:
    m.record(k, {"key": k}, d[k].encode())

state = {"i": 0}
def tick_sleep(s):
    state["i"] += 1
    open(TICK, "w").write(str(state["i"]))
m.run_ladder(observe, sleep=tick_sleep)
'''  % {"here": HERE}


def _run_e2e(td, fault):
    _write_store(td, {"kept": "k", "doomed": "d"})
    path = os.path.join(td, f"dw_{fault}.json")
    open(os.path.join(td, "tick"), "w").write("0")
    with tempfile.NamedTemporaryFile("w", suffix=".py", dir=td, delete=False) as f:
        f.write(_E2E_DRIVER)
        driver = f.name
    env = dict(os.environ, DW_TD=td, DW_PATH=path, DW_CASE=f"e2e_{fault}",
               DW_FAULT=fault, PYTHONHASHSEED="0")
    env.pop("ORACLE_SELFTEST", None)
    r = subprocess.run([sys.executable, driver], capture_output=True, text=True, env=env)
    return r.returncode, r.stdout + r.stderr


def group5_e2e():
    with tempfile.TemporaryDirectory() as td:
        rc_g, out_g = _run_e2e(td, "none")
        green_ok = rc_g == 0 and "VERDICT: GREEN" in out_g and "acked-effect-durable PASS" in out_g
    with tempfile.TemporaryDirectory() as td:
        rc_r, out_r = _run_e2e(td, "delete_after_delay")
        # the loss lands at a LATE rung — the invariant that fires must be t75s (not t0)
        red_ok = (rc_r == 1 and "VERDICT: RED" in out_r
                  and "durability_watch_t75s acked-effect-durable FAIL" in out_r
                  and "doomed" in out_r)
    ok = green_ok and red_ok
    print(f"  durable_baseline_GREEN={green_ok}  delayed_erasure_RED_at_t75s={red_ok} {_fmt(ok)}")
    if not ok:
        print("GREEN out:\n", out_g[-400:], "\nRED out:\n", out_r[-400:])
    return ok


def main():
    groups = [
        ("1 determinism/hashing (x50 processes)", group1_determinism),
        ("2 selftest fires RED", group2_selftest),
        ("3 restart-tolerance (kill mid-ladder, resume)", group3_restart),
        ("4 flap detection (nearmiss, still green)", group4_flap),
        ("5 end-to-end micro (green + #627-shape red)", group5_e2e),
    ]
    results = []
    for name, fn in groups:
        print(f"\n=== GROUP {name} ===")
        try:
            ok = fn()
        except Exception:
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
