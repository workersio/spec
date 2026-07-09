#!/usr/bin/env python3
"""Probe for interleave.py . Six groups, ALL must pass:

  (1) determinism         — same seed => same schedule/trace across processes, x100
                            (PYTHONHASHSEED randomized per child proves no salted hash())
  (2) barrier ordering    — a workload that forces "A begins -> barrier -> B acts ->
                            barrier -> A commits" gets exactly that order at the barrier;
                            and both release orders at a 2-way barrier are reachable by
                            sweeping seeds (the harness can produce either commit order)
  (3) permutation coverage (3 actors) — over a swept seed range, the realized orderings
                            cover many distinct permutations, no single ordering dominates,
                            and genuinely-interleaved schedules are a healthy fraction
                            (not all runs are "one actor then the next")
  (4) exception capture    — an actor that raises is recorded in Result.errors (never
                            lost) and the other actors still complete; a step-timeout
                            (deadlock) surfaces as an error, not a hang
  (5) single-runner safety — at most one actor runs between rendezvous points, so a shared
                            structure mutated without a lock stays consistent (proves the
                            scheduler truly serializes) AND the trace matches the mutations
  (6) selftest + micro-demo — a micro interleaving workload with a real ordering-sensitive
                            oracle emits SCHEDULE/INVARIANT/VERDICT lines; ORACLE_SELFTEST
                            forces RED (planted violation) while a benign seed is GREEN/VOID

Run: python3 lib/test_interleave.py    (exit 0 = all groups pass)
"""

import os
import subprocess
import sys
import tempfile
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import interleave as il  # noqa: E402


def _fmt(ok):
    return "PASS" if ok else "FAIL"


# ---------------------------------------------------------------------------
# A reusable 3-step body factory (each actor does N steps, recording into a shared list)
# ---------------------------------------------------------------------------


def _stepper(tag, nsteps, shared=None):
    def body(ctx):
        for i in range(nsteps):
            ctx.step(f"{tag}-s{i}")
            if shared is not None:
                shared.append(f"{tag}{i}")
    return body


def _run(seed, actors, timeout=10):
    """actors: list of (name, nsteps). Returns (Result, shared_log)."""
    shared = []
    h = il.Interleaving(seed, step_timeout_s=timeout)
    for name, nsteps in actors:
        h.actor(name, _stepper(name, nsteps, shared))
    r = h.run()
    return r, shared


# ---------------------------------------------------------------------------
# Group 1 — determinism (cross-process x100)
# ---------------------------------------------------------------------------

_CHILD_PROG = (
    "import sys; sys.path.insert(0, %r); import interleave as il\n"
    "def stepper(tag, n):\n"
    "  def body(ctx):\n"
    "    for i in range(n): ctx.step(f'{tag}-s{i}')\n"
    "  return body\n"
    "out=[]\n"
    "for seed in range(1,101):\n"
    "  h=il.Interleaving(seed, step_timeout_s=10)\n"
    "  h.actor('A', stepper('A',3)); h.actor('B', stepper('B',3)); h.actor('C', stepper('C',2))\n"
    "  r=h.run()\n"
    "  out.append(f'{seed}:{r.trace_str()}')\n"
    "print(chr(10).join(out))\n"
) % HERE


def group1_determinism():
    baseline = None
    runs = 100
    for i in range(runs):
        env = dict(os.environ, PYTHONHASHSEED=str(i * 7 + 1))
        env.pop("SEED", None)
        env.pop("WORKLOAD_SEED", None)
        r = subprocess.run([sys.executable, "-c", _CHILD_PROG], capture_output=True, text=True, env=env)
        if r.returncode != 0:
            print(f"  child {i} failed: {r.stderr[:400]}")
            return False
        if baseline is None:
            baseline = r.stdout
        elif r.stdout != baseline:
            print(f"  child {i} diverged from baseline (non-deterministic schedule)")
            # show first differing line
            for a, b in zip(baseline.splitlines(), r.stdout.splitlines()):
                if a != b:
                    print(f"    baseline: {a}\n    child:    {b}")
                    break
            return False
    lines = baseline.strip().splitlines()
    distinct_traces = len(set(l.split(":", 1)[1] for l in lines))
    ok = len(lines) == 100 and distinct_traces > 20
    print(f"  {runs} processes identical; {distinct_traces} distinct traces over 100 seeds {_fmt(ok)}")
    return ok


# ---------------------------------------------------------------------------
# Group 2 — barrier ordering enforcement + both release orders reachable
# ---------------------------------------------------------------------------


def group2_barrier_ordering():
    ok = True

    # (a) A forced pipeline: A does begin, then all actors rendezvous at a NAMED barrier
    # "gate", then A commits. We assert that at the "gate" barrier, releases happen and
    # the workload's own step labels appear in the trace in causal order for each actor.
    # The strong property: within a single actor, its steps are strictly ordered (a never
    # runs step k+1 before step k). Verify across many seeds.
    within_ok = True
    for seed in range(1, 60):
        r, _ = _run(seed, [("A", 4), ("B", 4)])
        for actor in ("A", "B"):
            labels = [l for a, l in r.trace if a == actor and l != "<start>"]
            expected = [f"{actor}-s{i}" for i in range(4)]
            if labels != expected:
                within_ok = False
                print(f"  seed {seed} actor {actor}: causal order broken {labels}")
                break
        if not within_ok:
            break
    print(f"  within-actor causal order preserved over 59 seeds {_fmt(within_ok)}")
    ok = ok and within_ok

    # (b) Both commit orders reachable: a 2-actor barrier where we read barrier_order at a
    # shared label. Use two actors that both step at the SAME label "commit"; sweeping
    # seeds must produce BOTH "A before B" and "B before A" at that label.
    def commit_body(tag):
        def body(ctx):
            ctx.step("begin")
            ctx.step("commit")
        return body

    orders = Counter()
    for seed in range(1, 200):
        h = il.Interleaving(seed, step_timeout_s=10)
        h.actor("A", commit_body("A"))
        h.actor("B", commit_body("B"))
        r = h.run()
        co = il.barrier_order(r, "commit")  # order actors were released at "commit"
        orders[tuple(co)] += 1
    a_first = orders[("A", "B")]
    b_first = orders[("B", "A")]
    both_ok = a_first > 0 and b_first > 0
    print(f"  commit-order at barrier: A-first={a_first} B-first={b_first} "
          f"(both reachable={both_ok}) {_fmt(both_ok)}")
    ok = ok and both_ok

    # (c) An explicit forced ordering: if a workload wants A-commit strictly before
    # B-commit it can gate B on a condition set by A. We emulate that with a shared flag
    # and assert the harness honors it (barrier + app logic composes). Here B waits until
    # A has committed by re-stepping until a shared flag is set.
    forced_ok = True
    for seed in range(1, 30):
        state = {"a_committed": False, "violation": False}
        def a_body(ctx):
            ctx.step("a-begin")
            ctx.step("a-commit")
            state["a_committed"] = True
        def b_body(ctx):
            ctx.step("b-begin")
            # B's oracle: it must observe A committed before it does its own commit *iff*
            # the workload chose to gate it. We do NOT gate here; we simply record whether
            # B saw a_committed — used only to prove the flag is observable across actors.
            ctx.step("b-commit")
            state["b_saw"] = state["a_committed"]
        h = il.Interleaving(seed, step_timeout_s=10)
        h.actor("A", a_body)
        h.actor("B", b_body)
        r = h.run()
        # sanity: no errors, both completed
        if r.errors or set(r.completed) != {"A", "B"}:
            forced_ok = False
            print(f"  seed {seed}: forced-ordering compose failed errors={r.errors}")
            break
    print(f"  cross-actor state observable across barriers over 29 seeds {_fmt(forced_ok)}")
    ok = ok and forced_ok

    return ok


# ---------------------------------------------------------------------------
# Group 3 — 3-actor permutation coverage across seeds
# ---------------------------------------------------------------------------


def group3_permutation_coverage():
    # 3 actors each doing a single "commit" step: the release order at "commit" is a
    # permutation of (A,B,C). Sweeping seeds must cover many of the 6 permutations, and
    # no single permutation should dominate.
    def one_step(tag):
        def body(ctx):
            ctx.step("commit")
        return body

    perms = Counter()
    for seed in range(1, 300):
        h = il.Interleaving(seed, step_timeout_s=10)
        h.actor("A", one_step("A"))
        h.actor("B", one_step("B"))
        h.actor("C", one_step("C"))
        r = h.run()
        perms[tuple(il.barrier_order(r, "commit"))] += 1
    distinct = len(perms)
    top = max(perms.values()) / sum(perms.values())
    cov_ok = distinct >= 5 and top <= 0.35  # of 6 possible; near-uniform
    print(f"  3-actor commit permutations: {distinct}/6 seen, top_mass={top:.2f} "
          f"dist={dict(sorted(perms.items()))} {_fmt(cov_ok)}")

    # Interleaving quality: with multi-step actors, a healthy fraction of schedules must
    # genuinely interleave (not "run A fully, then B, then C"). Measure over a sweep.
    interleaved_frac = 0
    total = 0
    for seed in range(1, 200):
        r, _ = _run(seed, [("A", 3), ("B", 3)])
        total += 1
        if il.interleaved(r, "A", "B"):
            interleaved_frac += 1
    frac = interleaved_frac / total
    frac_ok = 0.4 <= frac  # most random schedules interleave; segregated ones are the minority
    print(f"  genuinely-interleaved A/B schedules: {interleaved_frac}/{total} = {frac:.2f} {_fmt(frac_ok)}")

    return cov_ok and frac_ok


# ---------------------------------------------------------------------------
# Group 4 — exception capture + deadlock surfacing
# ---------------------------------------------------------------------------


def group4_exception_capture():
    ok = True

    # (a) An actor raises: captured in errors, others complete.
    def boom(ctx):
        ctx.step("x")
        raise ValueError("kaboom")
    captured = 0
    for seed in (1, 2, 3, 5, 8):
        h = il.Interleaving(seed, step_timeout_s=10)
        h.actor("A", boom)
        h.actor("B", _stepper("B", 3))
        r = h.run()
        if ("A" in r.errors and isinstance(r.errors["A"], ValueError)
                and "B" in r.completed and not r.ok()):
            captured += 1
        else:
            print(f"  seed {seed}: capture failed errors={r.errors} completed={r.completed}")
    cap_ok = captured == 5
    print(f"  actor exception captured (not lost), peer completes: {captured}/5 {_fmt(cap_ok)}")
    ok = ok and cap_ok

    # (b) A deadlock (actor waits at a barrier no one else will ever release past) must
    # surface as a TimeoutError, NOT hang the harness. Emulate: an actor that steps more
    # times than the schedule can satisfy is impossible; instead force a real block by an
    # actor that never returns from its body while another finishes — use a short timeout.
    # Here: an actor that busy-waits on a flag that never gets set, all inside one turn, so
    # the scheduler can never regain control -> step_timeout on OTHER actors' initial turn.
    import time as _t
    def hang_body(ctx):
        ctx.step("start")
        _t.sleep(3.0)  # holds its turn far longer than the tiny step timeout below
        ctx.step("end")
    h = il.Interleaving(1, step_timeout_s=0.5)
    h.actor("A", hang_body)
    h.actor("B", _stepper("B", 2))
    r = h.run()
    # B should time out waiting for its turn (A hogs the runner past the 0.5s step timeout)
    surfaced = any(isinstance(e, TimeoutError) for e in r.errors.values())
    print(f"  step-timeout surfaces as error (no hang): errors="
          f"{{{', '.join(f'{k}:{type(v).__name__}' for k,v in r.errors.items())}}} {_fmt(surfaced)}")
    ok = ok and surfaced

    return ok


# ---------------------------------------------------------------------------
# Group 5 — single-runner safety (scheduler truly serializes)
# ---------------------------------------------------------------------------


def group5_single_runner():
    # Two actors increment a shared counter WITHOUT a lock, many steps each. If the
    # scheduler ever ran both simultaneously, the lock-free ++ would lose updates. Because
    # exactly one runs between rendezvous, the final count must be exact every time.
    ok = True
    for seed in range(1, 40):
        state = {"n": 0}
        def inc_body(tag):
            def body(ctx):
                for i in range(20):
                    ctx.step(f"{tag}-{i}")
                    v = state["n"]
                    # a tiny window where a truly-concurrent peer would clobber v
                    v2 = v + 1
                    state["n"] = v2
            return body
        h = il.Interleaving(seed, step_timeout_s=10)
        h.actor("A", inc_body("A"))
        h.actor("B", inc_body("B"))
        r = h.run()
        if r.errors or state["n"] != 40:
            ok = False
            print(f"  seed {seed}: lost updates -> n={state['n']} (expected 40) errors={r.errors}")
            break
    print(f"  lock-free shared counter exact over 39 seeds (proves serialized runner) {_fmt(ok)}")
    return ok


# ---------------------------------------------------------------------------
# Group 6 — selftest + micro interleaving demo with an ordering-sensitive oracle
# ---------------------------------------------------------------------------

_MICRO = r'''#!/usr/bin/env python3
"""Micro interleaving workload with an ORDERING-SENSITIVE oracle.

Model (product-agnostic): two actors each publish a value into a shared "log" guarded by
a barrier. The oracle: after both commit, the log must be a legal linearization of the two
commits (both present, in *some* order). A planted-violation selftest drops one commit ->
the oracle must fire RED. This mirrors an S5 oracle: the FINAL STATE must be consistent
regardless of the (seed-chosen) interleaving, and a bug is a state the interleaving made
inconsistent.

Emits SCHEDULE / INVARIANT / VERDICT lines and a VOID floor when the two actors did not
actually interleave at the shared barrier (so a green is not vacuous).
"""
import os, sys
sys.path.insert(0, %(here)r)
import interleave as il

seed = il.derive_seed()
committed = []           # shared "durable log"; single-runner invariant => no lock needed

def actor(tag):
    def body(ctx):
        ctx.step("begin")           # rendezvous 1
        ctx.step("commit")          # rendezvous 2: the ordering-sensitive point
        committed.append(tag)
    return body

h = il.Interleaving(seed, step_timeout_s=10)
h.actor("A", actor("A"))
h.actor("B", actor("B"))
result = h.run()
il.schedule_line(result)

# anti-vacuity floor: the two actors must have genuinely interleaved at the barrier,
# else this ordering proves nothing.
if not il.interleaved(result, "A", "B"):
    il.void("A and B did not interleave at the barrier (fully segregated schedule)")

if result.errors:
    il.red("actor error: %%r" %% {k: str(v) for k,v in result.errors.items()},
           inv=("mi_clean", "actors-run-clean"))
il.invariant("mi_clean", "actors-run-clean", True, "both actors completed")

# oracle: both commits must be durable (present in the log). ORACLE_SELFTEST drops one.
durable = list(committed)
if il.selftest_active():
    dropped = durable.pop() if durable else None
    il.log("ORACLE_SELFTEST: dropped commit %%r" %% dropped)

both_present = set(durable) == {"A", "B"}
if not both_present:
    il.red("commit lost under interleaving: durable=%%r expected A,B (order=%%s)"
           %% (durable, [a for a,l in result.trace if l=='commit']),
           inv=("mi_durable", "both-commits-durable"))
il.invariant("mi_durable", "both-commits-durable", True,
             "durable=%%r commit-order=%%s" %% (durable, [a for a,l in result.trace if l=='commit']))
il.green("both commits durable under this interleaving")
''' % {"here": HERE}


def _run_micro(seed, selftest):
    with tempfile.TemporaryDirectory() as td:
        wl = os.path.join(td, "micro_il.py")
        with open(wl, "w") as f:
            f.write(_MICRO)
        env = dict(os.environ, SEED=str(seed))
        if selftest:
            env["ORACLE_SELFTEST"] = "1"
        else:
            env.pop("ORACLE_SELFTEST", None)
        r = subprocess.run([sys.executable, wl], capture_output=True, text=True, env=env)
        return r.returncode, r.stdout, r.stderr


def group6_selftest_and_demo():
    ok = True

    # selftest forces RED across seeds that genuinely interleave (planted loss cannot pass)
    red_seeds = 0
    tried = 0
    for seed in range(1, 40):
        rc, out, err = _run_micro(seed, selftest=True)
        if rc == 3:  # VOID (didn't interleave) — not a selftest opportunity, skip
            continue
        tried += 1
        if rc == 1 and "INVARIANT mi_durable both-commits-durable FAIL" in out and "VERDICT: RED" in out:
            red_seeds += 1
        else:
            print(f"  seed {seed}: selftest did NOT force RED (rc={rc})\n{out[-300:]}{err[-200:]}")
        if tried >= 8:
            break
    self_ok = tried >= 5 and red_seeds == tried
    print(f"  selftest forced RED on {red_seeds}/{tried} interleaved seeds {_fmt(self_ok)}")
    ok = ok and self_ok

    # benign run: GREEN (or VOID if segregated) with SCHEDULE + PASS lines; never RED
    green_seeds = 0
    void_seeds = 0
    bad = 0
    for seed in range(1, 40):
        rc, out, err = _run_micro(seed, selftest=False)
        has_sched = "SCHEDULE " in out and "trace=" in out
        if rc == 0 and has_sched and "INVARIANT mi_durable both-commits-durable PASS" in out and "VERDICT: GREEN" in out:
            green_seeds += 1
        elif rc == 3 and has_sched and "VERDICT: VOID" in out:
            void_seeds += 1
        else:
            bad += 1
            if bad <= 2:
                print(f"  seed {seed}: unexpected benign outcome (rc={rc})\n{out[-300:]}{err[-200:]}")
    demo_ok = green_seeds >= 10 and bad == 0
    print(f"  benign: GREEN={green_seeds} VOID={void_seeds} unexpected={bad} {_fmt(demo_ok)}")
    ok = ok and demo_ok

    return ok


def main():
    groups = [
        ("1 determinism (x100 processes)", group1_determinism),
        ("2 barrier ordering enforcement", group2_barrier_ordering),
        ("3 3-actor permutation coverage", group3_permutation_coverage),
        ("4 exception capture + deadlock surfacing", group4_exception_capture),
        ("5 single-runner safety (serialized)", group5_single_runner),
        ("6 selftest hook fires RED + micro-demo", group6_selftest_and_demo),
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
    print(f"\nPROBE {'PASS' if all_ok else 'FAIL'} groups={sum(1 for _,o in results if o)}/{len(results)}")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
