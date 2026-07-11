#!/usr/bin/env python3
"""run_scenario -- the executable spine: one scenario + one seed = one workload case.

Ships with the wio workload-harness skill; copy into the repo's .workers/lib/. Lives
at ``.workers/lib/run_scenario.py`` inside a connected repo and is invoked once per
wio case:

    python3 .workers/lib/run_scenario.py <scenario.md> [--seed N] [--redproof] [--list-plan]

Design contract (see CONTRACT.md §run_scenario.py), in order:
  1. Resolve the seed (``--seed`` > ``WIO_SEED`` > urandom-derived) and print ``SEED <n>``.
  2. Load the scenario frontmatter and the usage model (``.workers/usage-model.md``).
  3. Import the flow module ``.workers/flows/flows_<target>.py`` (FLOWS / make_sut / EVENTS).
  4. build_plan() and print the PLAN line; ``--list-plan`` stops here.
  5. Arm the SIGALRM liveness watchdog (``WIO_WATCHDOG_S``, default 240).
  6. Run actors: 1 -> inline, >1 -> interleave's seeded scheduler. Arm the scenario
     event over the merged op-index stream and fire it when the barrier count passes.
  7. ``--redproof``: corrupt ONE oracle channel (observation side only) and prove the
     checks flip RED -- ``ORACLE_SELFTEST PASS`` (exit 0) if they do, ``FAIL`` (exit 1)
     if the oracle swallowed the planted violation.
  8. Run every oracle: persona ledgers, error contract, wall clock, + optional flow
     ``sweep(sut)`` terminal-state hook.
  9. Verdict: any FAIL -> ``VERDICT RED`` (1); all channels vacuous -> ``VERDICT VOID``
     (3); else ``VERDICT GREEN`` (0). ``sut.stop()`` in ``finally``.
  10. Setup problems (boot / import failure) -> ``setup-block: <why>`` on stderr, exit 44.

Determinism: all randomness flows through ``genlib.seeded_rng`` and crashclock's
process-independent seed mapping; the only wall-clock reads are the watchdog and the
wall-clock oracle. No product nouns live here.

The three per-actor oracle modules (personaledger / errorcontract / wallclock) are the
canonical implementations copied alongside this file. Where one is not importable this
spine falls back to a byte-compatible in-module shim so a case still runs; the canonical
module is always preferred when present.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import signal
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import crashclock  # noqa: E402
import interleave  # noqa: E402
import scenario_gen  # noqa: E402
from genlib import root_seed_from, seeded_rng  # noqa: E402


def log(msg: str) -> None:
    print(msg, flush=True)


class SetupError(Exception):
    """A boot/import failure -- surfaced as ``setup-block`` (exit 44), never a verdict."""


# ---------------------------------------------------------------------------
# Oracle channels: prefer the canonical modules, fall back to compatible shims
# ---------------------------------------------------------------------------

@dataclass
class _Vio:
    actor: str
    code: str
    kind: str
    key: str
    detail: str


try:  # persona ledger -- canonical module exists in this dir
    from personaledger import PersonaLedger, check_all as ledger_check_all  # noqa: F401
except Exception:  # pragma: no cover - fallback path
    class PersonaLedger:  # type: ignore[no-redef]
        def __init__(self, actor_id: str):
            self.actor_id = actor_id
            self._acked: dict = {}
            self._denied: dict = {}
            self._obs: dict = {}

        def acked(self, kind, key, value=None):
            self._acked[(kind, key)] = value

        def denied(self, kind, key, reason=""):
            self._denied[(kind, key)] = reason

        def observe(self, kind, key, value=None, present=True):
            self._obs[(kind, key)] = (present, value)

        def check(self):
            vios = []
            for (kind, key), av in self._acked.items():
                obs = self._obs.get((kind, key))
                if obs is None or not obs[0]:
                    vios.append(_Vio(self.actor_id, "acked_lost", kind, key,
                                     f"{kind}/{key} acked but not observed"))
                elif av is not None and obs[1] != av:
                    vios.append(_Vio(self.actor_id, "acked_mutated", kind, key,
                                     f"{kind}/{key} acked={av!r} observed={obs[1]!r}"))
            for (kind, key), _r in self._denied.items():
                obs = self._obs.get((kind, key))
                if obs is not None and obs[0]:
                    vios.append(_Vio(self.actor_id, "denied_happened", kind, key,
                                     f"{kind}/{key} denied but observed present"))
            return vios

        def redproof_corrupt(self, rng):
            ak = list(self._acked.keys())
            if ak:
                kind, key = ak[rng.randrange(len(ak))]
                self._obs[(kind, key)] = (False, None)
                log(f"ORACLE_SELFTEST PLANTED ledger {self.actor_id} {kind}/{key}")
                return
            dk = list(self._denied.keys())
            if dk:
                kind, key = dk[rng.randrange(len(dk))]
                self._obs[(kind, key)] = (True, None)
                log(f"ORACLE_SELFTEST PLANTED ledger {self.actor_id} {kind}/{key}")

        @property
        def vacuous(self):
            return not self._acked and not self._denied

    def ledger_check_all(ledgers, emit=print):  # type: ignore[no-redef]
        ledgers = list(ledgers)
        any_nonvacuous = any(not lg.vacuous for lg in ledgers)
        any_violation = False
        for lg in ledgers:
            vios = lg.check()
            n = len(vios)
            if n:
                any_violation = True
            detail = vios[0].detail if vios else "-"
            emit(f"INVARIANT ledger_{lg.actor_id} persona-ledger "
                 f"{'FAIL' if n else 'PASS'} {n} {detail}")
        if not any_nonvacuous:
            return "VOID"
        return "RED" if any_violation else "GREEN"


try:  # error contract -- may not exist yet (written concurrently); shim if absent
    from errorcontract import ErrorContract, check_contract  # noqa: F401
except Exception:
    class ErrorContract:  # type: ignore[no-redef]
        def __init__(self, documented=None):
            self.documented = documented or {}
            self._ops: list = []  # [label, status, detail]

        @contextmanager
        def expect(self, op_label, outcome="any", fatal=False):
            rec = [op_label, "success", ""]
            self._ops.append(rec)
            try:
                yield
            except BaseException as exc:  # noqa: BLE001
                docs = self.documented.get(op_label, ())
                if docs and isinstance(exc, docs):
                    rec[1], rec[2] = "documented_error", type(exc).__name__
                else:
                    rec[1] = "undocumented_error"
                    rec[2] = f"{type(exc).__name__}: {exc}"
                    if fatal:
                        raise
                return
            if outcome == "must-fail":
                rec[1], rec[2] = "silent_success", "expected failure, got success"

        def check(self):
            return [_Vio("error_contract", s, lbl, lbl, d)
                    for lbl, s, d in self._ops
                    if s in ("undocumented_error", "silent_success")]

        def redproof_corrupt(self, rng):
            cand = [r for r in self._ops if r[1] in ("success", "documented_error")]
            if cand:
                r = cand[rng.randrange(len(cand))]
                r[1], r[2] = "undocumented_error", "planted undocumented outcome"
                log(f"ORACLE_SELFTEST PLANTED errors {r[0]}")

        @property
        def vacuous(self):
            return not self._ops

    def check_contract(contract, emit=print):  # type: ignore[no-redef]
        vios = contract.check()
        n = len(vios)
        emit(f"INVARIANT error_contract error-contract "
             f"{'FAIL' if n else 'PASS'} {n} {vios[0].detail if vios else '-'}")
        if contract.vacuous:
            return "VOID"
        return "RED" if n else "GREEN"


try:  # wall clock -- may not exist yet; shim if absent
    from wallclock import WallClock, check_clock  # noqa: F401
except Exception:
    class WallClock:  # type: ignore[no-redef]
        def __init__(self):
            self._recs: list = []  # [label, elapsed, max_s]

        @contextmanager
        def bound(self, label, max_s):
            rec = [label, 0.0, float(max_s)]
            self._recs.append(rec)
            start = time.monotonic()
            try:
                yield
            finally:
                rec[1] = time.monotonic() - start

        def check(self):
            return [_Vio("wall_clock", "latency_exceeded", lbl, lbl,
                         f"{lbl} {el:.4g}s > {mx}s")
                    for lbl, el, mx in self._recs if el > mx]

        def redproof_corrupt(self, rng):
            if self._recs:
                r = self._recs[rng.randrange(len(self._recs))]
                r[1] = r[2] + 1.0
                log(f"ORACLE_SELFTEST PLANTED clock {r[0]}")

        @property
        def vacuous(self):
            return not self._recs

    def check_clock(clock, emit=print):  # type: ignore[no-redef]
        vios = clock.check()
        n = len(vios)
        emit(f"INVARIANT wall_clock wall-clock "
             f"{'FAIL' if n else 'PASS'} {n} {vios[0].detail if vios else '-'}")
        if clock.vacuous:
            return "VOID"
        return "RED" if n else "GREEN"


# ---------------------------------------------------------------------------
# The op clock: counts ctx.step barriers and fires the armed event once
# ---------------------------------------------------------------------------

class OpClock:
    """A shared, lock-guarded counter over the merged op stream.

    Every ``ctx.step`` call ticks it; when the count first passes the plan's armed
    op index, it fires ``EVENTS[key](sut)`` exactly once and logs
    ``CLOCK fired <key> at-op <n>`` (crashclock's line idiom).
    """

    def __init__(self, event, events_map, sut):
        self._lock = threading.Lock()
        self.count = 0
        self._event = event
        self._events = events_map or {}
        self._sut = sut
        self._fired = False

    def tick(self) -> None:
        fire_key = None
        with self._lock:
            self.count += 1
            if (self._event is not None and not self._fired
                    and self.count >= self._event.op_index):
                self._fired = True
                fire_key = self._event.key
                fire_n = self.count
        if fire_key is not None:
            log(f"CLOCK fired {fire_key} at-op {fire_n}")
            fn = self._events.get(fire_key)
            if fn is not None:
                fn(self._sut)


# ---------------------------------------------------------------------------
# The flow context handed to Flow.run(ctx)
# ---------------------------------------------------------------------------

class FlowCtx:
    """One actor's view: identity, per-actor rng, the three oracle channels, the SUT,
    and the ``step`` barrier. ``step`` ticks the op clock (global event timing) and, in
    a multi-actor plan, blocks on interleave's scheduler; inline it is a pure tick."""

    def __init__(self, actor, sut, ledger, errors, clock, rng, opclock, barrier=None):
        self.actor_id = actor.actor_id
        self.persona = actor.persona
        self.rng = rng
        self.ledger = ledger
        self.errors = errors
        self.clock = clock
        self.sut = sut
        self._opclock = opclock
        self._barrier = barrier

    def step(self, label: str) -> None:
        self._opclock.tick()
        if self._barrier is not None:
            self._barrier(label)


# ---------------------------------------------------------------------------
# Flow-module load
# ---------------------------------------------------------------------------

def _find_workers_root(scenario_path: Path) -> Path:
    """Walk up from the scenario file to the ``.workers`` root (the dir holding
    ``usage-model.md``)."""
    start = scenario_path.resolve().parent
    for cand in [start, *start.parents]:
        if (cand / "usage-model.md").exists():
            return cand
    raise SetupError(f"usage-model.md not found above {scenario_path}")


def _load_flow_module(root: Path, target: str):
    path = root / "flows" / f"flows_{target}.py"
    if not path.exists():
        raise SetupError(f"flow module not found: {path}")
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))  # let the flow module import the ``flows`` package
    try:
        spec = importlib.util.spec_from_file_location(f"flows_{target}", str(path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as exc:  # noqa: BLE001
        raise SetupError(f"flow module import failed: {exc}") from exc
    for attr in ("FLOWS", "make_sut", "EVENTS"):
        if not hasattr(mod, attr):
            raise SetupError(f"flow module missing {attr}")
    return mod


# ---------------------------------------------------------------------------
# Actor execution
# ---------------------------------------------------------------------------

def _run_actors(plan, flowmod, sut, ledgers, errors, clock, opclock, root) -> dict:
    """Run the plan's actors, returning ``{actor_id: exception}`` for any that raised."""
    FLOWS = flowmod.FLOWS
    actor_errors: dict = {}

    def _rng(actor):
        return seeded_rng(root, f"actor:{actor.actor_id}")

    if len(plan.actors) == 1:
        a = plan.actors[0]
        ctx = FlowCtx(a, sut, ledgers[a.actor_id], errors, clock, _rng(a), opclock)
        try:
            for fkey in a.flow_seq:
                FLOWS[fkey]().run(ctx)
        except BaseException as exc:  # noqa: BLE001 - captured, never lost
            actor_errors[a.actor_id] = exc
        return actor_errors

    # The scheduler's per-step timeout must be subordinate to the liveness
    # watchdog, never a second tighter clock: under a virtual-time sandbox a
    # single legitimate step (an enqueue drained by a polling worker, a slow
    # boot) can cost minutes of virtual time, and the 30s library default
    # false-reds it as "blocked at barrier". WIO_STEP_TIMEOUT_S overrides;
    # otherwise inherit the watchdog budget (true hangs still convert via the
    # watchdog and the runtime's wall-clock timeout).
    step_timeout = float(
        os.environ.get("WIO_STEP_TIMEOUT_S", os.environ.get("WIO_WATCHDOG_S", "240"))
    )
    inter = interleave.Interleaving(plan.seed, step_timeout_s=step_timeout)

    def make_body(actor):
        def body(ictx):
            ctx = FlowCtx(actor, sut, ledgers[actor.actor_id], errors, clock,
                          _rng(actor), opclock, barrier=ictx.step)
            for fkey in actor.flow_seq:
                FLOWS[fkey]().run(ctx)
        return body

    for a in plan.actors:
        inter.actor(a.actor_id, make_body(a))
    result = inter.run()
    interleave.schedule_line(result)
    for name, exc in result.errors.items():
        actor_errors[name] = exc
    return actor_errors


# ---------------------------------------------------------------------------
# Checks + verdict
# ---------------------------------------------------------------------------

def _run_checks(ledgers_list, errors, clock, flowmod, sut, actor_errors) -> str:
    """Emit every oracle's INVARIANT line and fold the aggregate verdict."""
    verdicts = [
        ledger_check_all(ledgers_list),
        check_contract(errors),
        check_clock(clock),
    ]
    sweep_fail = False
    sweep_fn = getattr(flowmod, "sweep", None)
    if callable(sweep_fn):
        vios = sweep_fn(sut) or []
        n = len(vios)
        detail = vios[0].detail if (vios and hasattr(vios[0], "detail")) else "-"
        log(f"INVARIANT terminal_sweep terminal-state {'FAIL' if n else 'PASS'} {n} {detail}")
        sweep_fail = bool(n)
    for name, exc in actor_errors.items():
        log(f"INVARIANT flow_crash_{name} flow-crash FAIL 1 {type(exc).__name__}: {exc}")

    if "RED" in verdicts or sweep_fail or actor_errors:
        return "RED"
    if all(v == "VOID" for v in verdicts):
        return "VOID"
    return "GREEN"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _resolve_seed(arg_seed) -> int:
    if arg_seed is not None:
        return int(arg_seed)
    env = int(os.environ.get("WIO_SEED", "0") or "0")
    if env:
        return env
    return root_seed_from(os.urandom(8).hex()) & 0xFFFFFFFF


def _install_watchdog() -> None:
    if not hasattr(signal, "SIGALRM"):
        return
    seconds = int(float(os.environ.get("WIO_WATCHDOG_S", "240")))

    def _fire(signum, frame):  # noqa: ARG001
        log("INVARIANT liveness_watchdog liveness FAIL hang")
        os._exit(1)

    signal.signal(signal.SIGALRM, _fire)
    signal.alarm(max(1, seconds))


def _disarm_watchdog() -> None:
    if hasattr(signal, "SIGALRM"):
        signal.alarm(0)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run one workload scenario case.")
    ap.add_argument("scenario")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--redproof", action="store_true")
    ap.add_argument("--list-plan", action="store_true")
    args = ap.parse_args(argv)

    seed = _resolve_seed(args.seed)
    log(f"SEED {seed}")

    scenario_path = Path(args.scenario)
    sut = None
    try:
        import frontmatter as fm
        try:
            meta, _body = fm.load(scenario_path)
        except Exception as exc:  # noqa: BLE001
            raise SetupError(f"cannot load scenario {scenario_path}: {exc}") from exc

        root_dir = _find_workers_root(scenario_path)
        try:
            model, _mbody = fm.load(root_dir / "usage-model.md")
        except Exception as exc:  # noqa: BLE001
            raise SetupError(f"cannot load usage model: {exc}") from exc
        target = model.get("target")
        if not target:
            raise SetupError("usage-model.md missing 'target'")

        flowmod = _load_flow_module(root_dir, str(target))

        plan = scenario_gen.build_plan(meta, model, seed)
        log(plan.line())
        if args.list_plan:
            return 0

        root_seed = scenario_gen._plan_root(meta, seed)
        _install_watchdog()

        try:
            sut = flowmod.make_sut(meta, seed)
        except Exception as exc:  # noqa: BLE001
            raise SetupError(f"SUT failed to boot: {exc}") from exc

        # Build the oracle channels and the shared op clock.
        ledgers = {a.actor_id: PersonaLedger(a.actor_id) for a in plan.actors}
        used_flows = {f for a in plan.actors for f in a.flow_seq}
        documented: dict = {}
        for fkey in used_flows:
            cls = flowmod.FLOWS.get(fkey)
            documented.update(getattr(cls, "documented", {}) or {})
        errors = ErrorContract(documented)
        clock = WallClock()
        opclock = OpClock(plan.event, getattr(flowmod, "EVENTS", {}), sut)

        actor_errors = _run_actors(plan, flowmod, sut, ledgers, errors, clock,
                                   opclock, root_seed)
        _disarm_watchdog()

        ledgers_list = list(ledgers.values())

        if args.redproof:
            rng = seeded_rng(root_seed, "redproof")
            _redproof_corrupt(rng, ledgers_list, errors, clock)
            verdict = _run_checks(ledgers_list, errors, clock, flowmod, sut, actor_errors)
            if verdict == "RED":
                log("ORACLE_SELFTEST PASS")
                return 0
            log("ORACLE_SELFTEST FAIL oracle-swallowed-planted-violation")
            return 1

        verdict = _run_checks(ledgers_list, errors, clock, flowmod, sut, actor_errors)
        log(f"VERDICT {verdict}")
        return {"RED": 1, "VOID": 3, "GREEN": 0}[verdict]

    except SetupError as exc:
        _disarm_watchdog()
        print(f"setup-block: {exc}", file=sys.stderr, flush=True)
        return 44
    finally:
        _disarm_watchdog()
        if sut is not None:
            try:
                sut.stop()
            except Exception:  # noqa: BLE001 - stop() must never mask the verdict
                pass


def _redproof_corrupt(rng, ledgers_list, errors, clock) -> None:
    """Corrupt ONE non-vacuous oracle channel (observation side only) so the checks
    must flip RED. Prefer channels that actually witnessed something, else there is
    nothing to plant."""
    channels: list = []
    for lg in ledgers_list:
        if not lg.vacuous:
            channels.append(("ledger", lg))
    if not errors.vacuous:
        channels.append(("errors", errors))
    if not clock.vacuous:
        channels.append(("clock", clock))
    if not channels:
        return
    _kind, chan = channels[rng.randrange(len(channels))]
    chan.redproof_corrupt(rng)


if __name__ == "__main__":
    sys.exit(main())
