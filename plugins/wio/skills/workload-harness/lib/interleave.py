#!/usr/bin/env python3
"""Interleaving harness — turn ``--depth N`` into an N-point search over the ORDERING
of 2-3 concurrent actors (the interleaving class: e.g. DBOS #742, Turso MVCC ordering bugs).

Ships with the wio workload-harness skill; copy into the repo's .workers/lib/.
The wio runtime gives NO schedule control beyond the seed (no PCT, no
mutate-near-seed), so interleaving search lives at the WORKLOAD level — near-term
interleaving search is workload-level (barriers + seeded permutations of 2-3
actors). This module is that level.

The problem it solves
---------------------
An S5 bug needs a *specific ordering* between 2+ concurrent actors that ordinary volume
rarely produces (TOCTOU, stale-snapshot, write-write ordering). Hand-written interleaving workloads typically
HAND-FREEZE one ordering (writer begins -> DDL on a fresh conn -> commit).
That is a single frozen point, not a search. This library instead lets a **seed** drive:

  * the order in which actors are released at each rendezvous point, AND
  * (optionally) each actor's op/DDL/table choices drawn from parameterized pools,

so sweeping seeds sweeps orderings, and the red appears at *some* seed(s) within a swept
range — never a hand-frozen single ordering.

Core model
----------
Actors are plain Python callables run on threads (or, where the target needs separate
connections, each actor drives its own subprocess connection — see ``ConnActor`` in the
demo). They cooperate through a central **scheduler** that owns:

  * **named barriers**: ``ctx.step("label")`` blocks the calling actor and registers it
    "ready at label"; the scheduler releases exactly one ready actor at a time, in a
    **seed-chosen order**. This is how a workload forces
    "A begins txn -> barrier -> B commits DDL -> barrier -> A commits" AND its permutations.
  * **seeded permutation**: at every release point the scheduler consults a deterministic
    ``Schedule`` (a pure function of the seed) to pick which ready actor proceeds next.
    Same seed => same schedule; sweeping seeds sweeps orderings.
  * **per-actor exception capture**: an actor that raises is recorded, not lost; its
    exception is re-surfaced in the result so a red is adjudicable.
  * **a schedule trace**: the ordered list of ``(actor, label)`` releases, printable, so a
    red's ordering is reproducible from the trace + seed alone.

Determinism contract
---------------------
``Schedule(seed)`` is a pure function of the seed (splitmix64 / FNV-1a — process
independent, NOT Python's salted ``hash()``). Given the same actors performing the same
number of ``step`` calls in the same causal structure, the same seed yields the same
release order. The trace records the realized order so replay needs only (seed, trace).

Emitted contract (same conventions as crashclock.py / genlib.py):
  * ``SCHEDULE <seed> trace=<a@l,b@l,...>`` — one line per case, so sweep triage can
    bucket reds by realized ordering and a red is replayable from the trace.
  * standard ``INVARIANT``/``VERDICT`` lines (the workload's own oracle) + ``void()``
    anti-vacuity floors — an ordering that never actually interleaved is theater.
  * ``ORACLE_SELFTEST`` — a workload hook that plants a violation so the machinery must
    emit RED (proves the oracle isn't vacuously green).

Exit codes (corpus convention): 0 green, 1 red (finding), 3 void/blocked.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# ---------------------------------------------------------------------------
# Deterministic seed -> choice mapping (process-independent; matches crashclock)
# ---------------------------------------------------------------------------

_MASK64 = (1 << 64) - 1


def _splitmix64(x: int) -> int:
    x = (x + 0x9E3779B97F4A7C15) & _MASK64
    x = ((x ^ (x >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
    x = ((x ^ (x >> 27)) * 0x94D049BB133111EB) & _MASK64
    return x ^ (x >> 31)


def _hash_str(s: str) -> int:
    """Deterministic 64-bit FNV-1a hash of a string — process-independent."""
    h = 0xCBF29CE484222325
    for b in s.encode("utf-8"):
        h = ((h ^ b) * 0x100000001B3) & _MASK64
    return h


def substream(seed: int, axis: str) -> int:
    """A deterministic 64-bit value for one named axis of one seed."""
    return _splitmix64((seed & _MASK64) ^ _hash_str(axis))


def rand_unit(seed: int, axis: str) -> float:
    """Deterministic float in [0, 1) for (seed, axis)."""
    return (substream(seed, axis) >> 11) / float(1 << 53)


def rand_below(seed: int, axis: str, n: int) -> int:
    """Deterministic int in [0, n) for (seed, axis). n>=1."""
    if n <= 1:
        return 0
    return int(substream(seed, axis)) % n


def choice(seed: int, axis: str, pool: "list") -> Any:
    """Deterministically pick one element of ``pool`` for (seed, axis).

    This is the *generic* choice primitive actor bodies use so the seed drives BOTH the
    schedule and the op/DDL/table choices — never a bug-specific constant tuple.
    """
    if not pool:
        raise ValueError("choice() from empty pool")
    return pool[rand_below(seed, axis, len(pool))]


def derive_seed() -> int:
    """Seed source: env (SEED / WORKLOAD_SEED) else /dev/urandom — corpus convention.

    The runtime sets SEED=1..depth (sequential). Downstream is
    deterministic given this.
    """
    for key in ("SEED", "WORKLOAD_SEED"):
        env = os.environ.get(key)
        if env:
            return int(env, 0) & 0xFFFFFFFF
    with open("/dev/urandom", "rb") as f:
        return int.from_bytes(f.read(4), "little")


# ---------------------------------------------------------------------------
# Schedule — the seeded permutation policy
# ---------------------------------------------------------------------------


class Schedule:
    """Seeded release policy: at each release point, pick which READY actor proceeds.

    A ``Schedule`` is a *pure function of the seed*: given the same sequence of
    "which actors are ready right now" decisions, the same seed produces the same
    picks. The scheduler consults ``pick()`` every time >=1 actor is waiting at a
    barrier; the returned actor is released and runs until its next ``step`` (or it
    finishes). This realizes an arbitrary interleaving of the actors' step sequences.

    The pick is drawn from a per-decision substream keyed by the seed and a monotonically
    increasing decision index, so two decisions with the same ready-set do NOT lock-step.
    """

    def __init__(self, seed: int):
        self.seed = seed & _MASK64
        self._decision = 0

    def pick(self, ready: "list[str]") -> str:
        """Pick one actor name from the sorted ``ready`` set for this decision point.

        ``ready`` is sorted by the caller for determinism (set iteration order is not
        stable). The choice is uniform over the ready set under the seed's substream.
        """
        assert ready, "pick() from empty ready set"
        idx = rand_below(self.seed, f"sched:{self._decision}", len(ready))
        self._decision += 1
        return ready[idx]

    def decisions_made(self) -> int:
        return self._decision


# ---------------------------------------------------------------------------
# Actor context — what an actor body sees
# ---------------------------------------------------------------------------


@dataclass
class ActorContext:
    """Handle passed to each actor body. Exposes the rendezvous primitive + the seed.

    ``step(label)`` is the barrier: it blocks this actor and yields control to the
    scheduler, which releases the next actor per the seeded schedule. When this actor is
    chosen again it returns from ``step`` and proceeds. ``label`` names the rendezvous so
    the trace is human-readable and a red is reproducible.

    ``seed`` and the ``rng_*`` helpers let the actor draw its op/DDL/table choices from
    parameterized pools under the SAME seed that drives the schedule — so a swept seed
    sweeps both ordering and choices.
    """

    name: str
    seed: int
    _harness: "Interleaving"
    scratch: dict = field(default_factory=dict)

    def step(self, label: str) -> None:
        """Rendezvous point: block until the scheduler releases this actor."""
        self._harness._rendezvous(self.name, label)

    # --- seeded choice helpers (per-actor axis namespacing so actors don't collide) ---
    def rng_below(self, axis: str, n: int) -> int:
        return rand_below(self.seed, f"{self.name}:{axis}", n)

    def rng_unit(self, axis: str) -> float:
        return rand_unit(self.seed, f"{self.name}:{axis}")

    def rng_choice(self, axis: str, pool: list) -> Any:
        return choice(self.seed, f"{self.name}:{axis}", pool)


# ---------------------------------------------------------------------------
# Interleaving — the harness
# ---------------------------------------------------------------------------


class ActorError(Exception):
    """Wraps an exception raised inside an actor body, tagged with the actor name."""

    def __init__(self, actor: str, exc: BaseException):
        super().__init__(f"actor {actor!r} raised: {type(exc).__name__}: {exc}")
        self.actor = actor
        self.exc = exc


@dataclass
class Result:
    """Outcome of one interleaved run."""

    seed: int
    trace: "list[tuple[str, str]]"  # ordered (actor, label) releases
    errors: "dict[str, BaseException]"  # actor name -> exception (empty if all clean)
    completed: "list[str]"  # actors that finished their body cleanly

    def trace_str(self) -> str:
        return ",".join(f"{a}@{l}" for a, l in self.trace)

    def ok(self) -> bool:
        return not self.errors


class Interleaving:
    """Owns barriers, the seeded scheduler, per-actor exception capture, and the trace.

    Usage::

        h = Interleaving(seed)
        h.actor("writer", writer_body)   # writer_body(ctx) -> None
        h.actor("ddl", ddl_body)
        result = h.run()                 # runs all actors concurrently under the schedule
        print("SCHEDULE", seed, "trace=" + result.trace_str())

    Concurrency model: each actor runs on its own thread. A single lock + condition
    variable serializes them so that AT MOST ONE actor runs at a time between rendezvous
    points — the scheduler releases one actor, it runs until its next ``step`` (or
    finish), then the scheduler picks again from whoever is now ready. This makes the
    interleaving fully determined by the seed (no OS-scheduler nondeterminism decides who
    proceeds), while the actors themselves remain ordinary blocking code that can drive
    real subprocess connections.
    """

    def __init__(self, seed: int, step_timeout_s: float = 30.0):
        self.seed = seed & _MASK64
        self.schedule = Schedule(self.seed)
        self.step_timeout_s = step_timeout_s
        self._actors: "list[tuple[str, Callable[[ActorContext], None]]]" = []
        self._cond = threading.Condition()
        self._running: Optional[str] = None  # name of the actor currently permitted to run
        self._waiting: "dict[str, str]" = {}  # name -> label it is blocked at (incl "<start>")
        self._parked: "set[str]" = set()      # actors that have registered & are awaiting a turn
        self._finished: "set[str]" = set()
        self._errors: "dict[str, BaseException]" = {}
        self._trace: "list[tuple[str, str]]" = []
        self._started = False

    def actor(self, name: str, body: Callable[[ActorContext], None]) -> None:
        """Register an actor. ``body(ctx)`` runs on its own thread; ``ctx.step(label)``
        rendezvouses. Names must be unique and are used in the trace + schedule keys."""
        if any(n == name for n, _ in self._actors):
            raise ValueError(f"duplicate actor name {name!r}")
        self._actors.append((name, body))

    # -- scheduler internals ------------------------------------------------

    def _actor_names(self) -> "list[str]":
        return sorted(n for n, _ in self._actors)

    def _rendezvous(self, name: str, label: str) -> None:
        """Called from inside an actor at ``ctx.step(label)``: mark this actor parked and
        blocked at ``label``, hand control back to the scheduler, and block until this
        actor is picked to run again. Fully event-driven — no polling."""
        with self._cond:
            self._waiting[name] = label
            self._parked.add(name)
            self._running = None
            self._cond.notify_all()  # wake the scheduler to pick the next runner
            deadline = time.monotonic() + self.step_timeout_s
            while self._running != name:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    # Deadlock / starvation: surface as an error, never hang the harness.
                    self._parked.discard(name)
                    raise TimeoutError(
                        f"actor {name!r} blocked at {label!r} for >{self.step_timeout_s}s "
                        f"(deadlock? waiting={self._waiting} finished={sorted(self._finished)})"
                    )
                self._cond.wait(timeout=remaining)

    def _run_actor_thread(self, name: str, body: Callable[[ActorContext], None]) -> None:
        # Register at the "<start>" barrier and block until the scheduler grants the first
        # turn. Registering as parked BEFORE waiting is what lets the scheduler's first
        # pick be seed-driven over the full actor set (no thread-launch-order dependence).
        with self._cond:
            self._waiting[name] = "<start>"
            self._parked.add(name)
            self._cond.notify_all()
            deadline = time.monotonic() + self.step_timeout_s
            while self._running != name:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._parked.discard(name)
                    self._errors.setdefault(
                        name, TimeoutError(f"actor {name!r} never granted initial turn"))
                    self._finished.add(name)
                    self._waiting.pop(name, None)
                    self._cond.notify_all()
                    return
                self._cond.wait(timeout=remaining)
        ctx = ActorContext(name=name, seed=self.seed, _harness=self)
        try:
            body(ctx)
        except BaseException as exc:  # capture, never lose — a red must be adjudicable
            self._errors[name] = exc
        finally:
            with self._cond:
                self._finished.add(name)
                self._parked.discard(name)
                self._waiting.pop(name, None)
                self._running = None
                self._cond.notify_all()

    def _scheduler_loop(self) -> None:
        """The scheduler: repeatedly pick a PARKED actor and release it, until all done.

        Purely event-driven: it waits on the condition variable and is notified whenever an
        actor parks (registers at a barrier / start), finishes, or yields. Exactly one
        actor is granted ``_running`` at a time; it runs until its next ``step`` (which
        re-parks it) or it finishes.
        """
        all_names = set(self._actor_names())
        # Overall watchdog: the scheduler itself must not hang if the *running* actor
        # blocks forever inside its body (a barrier timeout only fires for PARKED actors).
        overall_deadline = time.monotonic() + self.step_timeout_s * (len(all_names) + 2)
        with self._cond:
            while self._finished != all_names:
                if time.monotonic() > overall_deadline:
                    return  # run() reaps join timeouts; a stuck running actor is surfaced there
                if self._running is not None:
                    self._cond.wait(timeout=self.step_timeout_s)  # running; sleep until it yields
                    continue
                # Only pick once EVERY live (not-finished) actor is parked. Because exactly
                # one actor runs at a time, when nothing is running every live actor should
                # be parked at a barrier — the only exception is startup, where a thread has
                # not yet reached its first park. Waiting for full accounting makes even the
                # FIRST pick a seed-driven choice over the complete actor set, independent of
                # thread-launch order (the determinism contract).
                live = all_names - self._finished
                if live != self._parked:
                    self._cond.wait(timeout=self.step_timeout_s)  # some live actor not yet parked
                    continue
                ready = sorted(self._parked)
                if not ready:
                    self._cond.wait(timeout=self.step_timeout_s)
                    continue
                pick = self.schedule.pick(ready)
                label = self._waiting.get(pick, "<start>")
                self._trace.append((pick, label))
                self._parked.discard(pick)
                self._running = pick
                self._cond.notify_all()

    def run(self) -> Result:
        """Run all registered actors concurrently under the seeded schedule; return the
        realized trace + captured errors. Blocks until every actor finishes (or a step
        timeout fires, surfacing a deadlock)."""
        if self._started:
            raise RuntimeError("Interleaving.run() called twice")
        self._started = True
        threads = []
        for name, body in self._actors:
            t = threading.Thread(target=self._run_actor_thread, args=(name, body), name=f"actor:{name}")
            t.daemon = True
            threads.append(t)
        for t in threads:
            t.start()
        # The scheduler will only make its first pick once actors have parked; since each
        # actor parks itself before waiting, the scheduler's `ready` set fills in as
        # threads reach their wait. Start the scheduler concurrently — it blocks on the
        # condition until the first park notify arrives.
        sched = threading.Thread(target=self._scheduler_loop, name="scheduler")
        sched.daemon = True
        sched.start()
        overall = self.step_timeout_s * (len(self._actors) + 2)
        sched.join(timeout=overall)
        for t in threads:
            t.join(timeout=self.step_timeout_s)
        completed = sorted(self._finished - set(self._errors))
        return Result(seed=self.seed, trace=list(self._trace), errors=dict(self._errors), completed=completed)


# ---------------------------------------------------------------------------
# Case protocol: SCHEDULE trace lines, INVARIANT/VERDICT, VOID floors, selftest
# ---------------------------------------------------------------------------


def log(msg: str) -> None:
    print(msg, flush=True)


def schedule_line(result: "Result") -> None:
    """Emit the ``SCHEDULE <seed> trace=<...>`` triage line so a red is bucketable by
    realized ordering and replayable from (seed, trace)."""
    log(f"SCHEDULE {result.seed} decisions={len(result.trace)} trace={result.trace_str()}")


def invariant(inv_id: str, name: str, ok: bool, summary: str) -> None:
    """Structured line the wio runtime parses into the invariants panel."""
    log(f"INVARIANT {inv_id} {name} {'PASS' if ok else 'FAIL'} {summary}")


def red(msg: str, inv: Optional[tuple] = None) -> "None":
    """Emit a finding (exit 1). ``inv`` = (inv_id, name) for the failed invariant line."""
    if inv:
        invariant(inv[0], inv[1], False, msg)
    log(f"VERDICT: RED — {msg}")
    sys.exit(1)


def void(msg: str) -> "None":
    """Anti-vacuity floor (exit 3): the trial did not establish its precondition, e.g. the
    two actors never actually interleaved at the target barrier — a green would be
    meaningless, so it is VOID, not GREEN."""
    log(f"VERDICT: VOID — {msg}")
    sys.exit(3)


def green(msg: str = "") -> None:
    log(f"VERDICT: GREEN{(' — ' + msg) if msg else ''}")


def selftest_active() -> bool:
    """Workloads gate a planted-violation branch on this so a green run is quantified.

    Convention (matches crashclock / genlib): if ORACLE_SELFTEST is set, the workload
    injects a violation the oracle MUST catch as RED; the probe asserts RED fires.
    """
    return bool(os.environ.get("ORACLE_SELFTEST"))


# ---------------------------------------------------------------------------
# Interleaving-quality floor: did the schedule actually interleave the actors?
# ---------------------------------------------------------------------------


def interleaved(result: "Result", a: str, b: str) -> bool:
    """True iff actors ``a`` and ``b`` genuinely alternated at least once in the trace —
    i.e. the trace is not simply "all of a, then all of b". A schedule that ran one actor
    to completion before the other never exercised the ordering, so its oracle result is
    VOID, not evidence.

    "Interleaved" here means: somewhere in the trace, a release of ``a`` is immediately
    followed by a release of ``b`` (or vice-versa) with both still having later work — we
    detect it as: the two actors' releases are not fully segregated in trace order.
    """
    seq = [name for name, _ in result.trace if name in (a, b)]
    if a not in seq or b not in seq:
        return False
    # Fully segregated => the sequence is a-run then b-run (or b-run then a-run):
    # detect a single transition point. Interleaved => >1 transition.
    transitions = sum(1 for i in range(1, len(seq)) if seq[i] != seq[i - 1])
    return transitions >= 2


def barrier_order(result: "Result", label: str) -> "list[str]":
    """The order in which actors were released AT a given barrier label (for oracles that
    care 'who committed first'). Returns actor names in release order for that label."""
    return [name for name, l in result.trace if l == label]


__all__ = [
    # seed mapping
    "substream", "rand_unit", "rand_below", "choice", "derive_seed",
    # harness
    "Schedule", "ActorContext", "Interleaving", "Result", "ActorError",
    # protocol
    "log", "schedule_line", "invariant", "red", "void", "green", "selftest_active",
    # quality floors / trace helpers
    "interleaved", "barrier_order",
]
