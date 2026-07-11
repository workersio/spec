#!/usr/bin/env python3
"""Crash-clock library — turn ``--depth N`` into an N-point search over FAULT TIMING.

Ships with the wio workload-harness skill; copy into the repo's .workers/lib/.

The runtime supplies each case a **sequential seed** (1..depth). This module maps that
seed to a *point in a declared timing space*: same seed => same offsets, and the SPACE
(not the point) is what a workload declares, so an auditor sees the axis being swept,
not a magic constant. Generalizes S2's delete-straddle bisection (S2 #627) and
the ``acked_appends`` kill-after pattern.

There are NO runtime fault primitives (``--faults`` is netem-on-loopback only), so every
fault lives *inside* the workload: this library gives the workload the *when* (``offsets``)
and the *how* (``kill_self_child`` / ``restart_dependency`` / ``hold_lock``).

Contract emitted by any workload using this:
  * ``CLOCK <case> armed <space-point>`` — one event line per armed clock, so sweep
    triage can bucket reds by timing point.
  * standard ``INVARIANT``/``VERDICT`` lines (the workload's own oracle) + VOID
    anti-vacuity floors (``void()`` helper) — a kill that never landed inside its
    window is theater, not evidence.
  * ``ORACLE_SELFTEST`` — a workload hook that plants a loss so the machinery must
    emit RED (proves the oracle isn't vacuously green).

Timing spaces (declared data, see ``Space``):
  (a) op-index clocks      — kill after K ops, K swept over a declared range
  (b) latency-window clocks — kill T ms after arming, T swept log-uniform over 0..window
  (c) phase straddles      — arm around an awaited event: in-flight / just-acked /
                             settled (the fencing.sh trio, generalized)
  (d) multi-point schedules — kill-restart-kill / kill-during-recovery: an ordered
                             list of the above, each a sub-clock

Exit codes (corpus convention): 0 green, 1 red (finding), 3 void/blocked.
"""

from __future__ import annotations

import math
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# ---------------------------------------------------------------------------
# Deterministic seed -> point mapping
# ---------------------------------------------------------------------------
#
# The mapping MUST be a pure function of (seed, space): same seed => same offsets,
# across processes and machines. We derive independent sub-streams per named axis by
# hashing (seed, axis-name) with a fixed constant — NOT Python's salted hash() (which
# varies per process). splitmix64 is a well-mixed, dependency-free integer hash.

_MASK64 = (1 << 64) - 1


def _splitmix64(x: int) -> int:
    x = (x + 0x9E3779B97F4A7C15) & _MASK64
    x = ((x ^ (x >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
    x = ((x ^ (x >> 27)) * 0x94D049BB133111EB) & _MASK64
    return x ^ (x >> 31)


def _hash_str(s: str) -> int:
    """Deterministic 64-bit hash of a string (FNV-1a) — process-independent."""
    h = 0xCBF29CE484222325
    for b in s.encode("utf-8"):
        h = ((h ^ b) * 0x100000001B3) & _MASK64
    return h


def substream(seed: int, axis: str) -> int:
    """A deterministic 64-bit value for one named axis of one seed.

    Independent axes (e.g. 'K' and 'window') get uncorrelated streams so sweeping one
    does not accidentally lock-step another.
    """
    return _splitmix64((seed & _MASK64) ^ _hash_str(axis))


def _unit(seed: int, axis: str) -> float:
    """Deterministic float in [0, 1) for (seed, axis)."""
    return (substream(seed, axis) >> 11) / float(1 << 53)


def derive_seed() -> int:
    """Seed source: env (SEED / WORKLOAD_SEED) else /dev/urandom — corpus convention.

    The runtime sets SEED=1..depth. The mapping downstream is deterministic given this.
    """
    for key in ("SEED", "WORKLOAD_SEED"):
        env = os.environ.get(key)
        if env:
            return int(env, 0) & 0xFFFFFFFF
    with open("/dev/urandom", "rb") as f:
        return int.from_bytes(f.read(4), "little")


# ---------------------------------------------------------------------------
# Timing-space declarations (the audited axis)
# ---------------------------------------------------------------------------

# Phase-straddle points: WHERE (relative to an awaited event) a clock arms.
PHASES = ("in_flight", "just_acked", "settled")


@dataclass(frozen=True)
class OpIndexSpace:
    """(a) Kill after K ops, K uniform over [lo, hi]."""

    axis: str
    lo: int
    hi: int
    kind: str = "op_index"

    def point(self, seed: int) -> dict:
        span = self.hi - self.lo
        k = self.lo + (int(substream(seed, self.axis + ":K")) % (span + 1) if span >= 0 else 0)
        return {"kind": self.kind, "axis": self.axis, "K": k}


@dataclass(frozen=True)
class LatencyWindowSpace:
    """(b) Kill T ms after arming, T log-uniform over [floor_ms, window_ms].

    Log-uniform because the interesting failures cluster near t=0 (a tight race window)
    but must also cover the whole flush arm — a linear sweep starves the sub-ms region.
    """

    axis: str
    window_ms: float
    floor_ms: float = 0.0
    kind: str = "latency_window"

    def point(self, seed: int) -> dict:
        u = _unit(seed, self.axis + ":T")
        lo = max(self.floor_ms, 1e-3)
        hi = max(self.window_ms, lo)
        t_ms = lo * math.exp(u * math.log(hi / lo)) if hi > lo else lo
        # Reserve a slice of the range for the exact-zero corner (immediate kill).
        if _unit(seed, self.axis + ":zero") < 0.15:
            t_ms = 0.0
        return {"kind": self.kind, "axis": self.axis, "T_ms": t_ms, "window_ms": self.window_ms}


@dataclass(frozen=True)
class PhaseStraddleSpace:
    """(c) Arm around an awaited event: in_flight / just_acked / settled.

    ``settle_ms`` is how long past the ack the 'settled' point waits (a durability watch
    lands here — S2#627's +64s erasure needs a settled straddle, not an immediate one).
    """

    axis: str
    settle_ms: float = 0.0
    phases: tuple = PHASES
    kind: str = "phase_straddle"

    def point(self, seed: int) -> dict:
        idx = int(substream(seed, self.axis + ":phase")) % len(self.phases)
        phase = self.phases[idx]
        delay = self.settle_ms if phase == "settled" else 0.0
        return {"kind": self.kind, "axis": self.axis, "phase": phase, "settle_ms": delay}


@dataclass(frozen=True)
class ScheduleSpace:
    """(d) Multi-point schedule: an ordered list of sub-spaces, each a sub-clock.

    Models kill-restart-kill and kill-during-recovery: each leg draws its own point from
    an independent axis of the same seed, so the whole schedule is one deterministic draw.
    ``repeat`` is itself swept (a range) so depth varies how many recovery interrupts fire.
    """

    axis: str
    legs: tuple  # tuple of the (a)/(b)/(c) space objects
    repeat_lo: int = 1
    repeat_hi: int = 1
    kind: str = "schedule"

    def point(self, seed: int) -> dict:
        span = self.repeat_hi - self.repeat_lo
        rep = self.repeat_lo + (int(substream(seed, self.axis + ":rep")) % (span + 1) if span >= 0 else 0)
        legs = [leg.point(substream(seed, self.axis + f":leg{i}") & 0xFFFFFFFF)
                for i, leg in enumerate(self.legs)]
        return {"kind": self.kind, "axis": self.axis, "repeat": rep, "legs": legs}


Space = Any  # any of the *Space dataclasses above (all expose .point(seed) and .kind)


def offsets(seed: int, space: Space) -> dict:
    """Pure function: (seed, declared space) -> the concrete timing point for this case.

    Same seed + same space => identical dict, in every process. This is the whole
    contract; everything else (primitives, events) is plumbing around it.
    """
    return space.point(seed)


# ---------------------------------------------------------------------------
# Case protocol: CLOCK event lines, INVARIANT/VERDICT, VOID floors, selftest
# ---------------------------------------------------------------------------


def log(msg: str) -> None:
    print(msg, flush=True)


def clock_armed(case: str, point: dict) -> None:
    """Emit the ``CLOCK <case> armed <space-point>`` triage line.

    The point is rendered as compact key=val so a sweep-triage grep can bucket reds by
    timing point without JSON parsing.
    """
    kv = _render_point(point)
    log(f"CLOCK {case} armed {kv}")


def _render_point(point: dict) -> str:
    parts = []
    for k, v in point.items():
        if k == "legs":
            parts.append("legs=[" + ";".join(_render_point(leg) for leg in v) + "]")
        elif isinstance(v, float):
            parts.append(f"{k}={v:.4g}")
        else:
            parts.append(f"{k}={v}")
    return " ".join(parts)


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
    """Anti-vacuity floor: the trial did not establish its precondition (exit 3).

    e.g. the kill never landed inside its window, or too few ops were acked before it —
    a green here would be meaningless, so it is VOID, not GREEN.
    """
    log(f"VERDICT: VOID — {msg}")
    sys.exit(3)


def green(msg: str = "") -> None:
    log(f"VERDICT: GREEN{(' — ' + msg) if msg else ''}")


def selftest_active() -> bool:
    """Workloads gate a planted-loss branch on this so a green run is quantified.

    Convention (matches genlib / acked_appends): if ORACLE_SELFTEST is set, the workload
    injects a loss the oracle MUST catch as RED; the probe asserts RED fires.
    """
    return bool(os.environ.get("ORACLE_SELFTEST"))


# ---------------------------------------------------------------------------
# In-workload fault primitives (no runtime faults exist)
# ---------------------------------------------------------------------------


def kill_self_child(proc: "subprocess.Popen", mode: str = "sigkill",
                    stop_dur_s: float = 0.0) -> str:
    """Kill/pause the product process the workload spawned.

    mode='sigkill'   : SIGKILL (hard crash — the S2#627 / acked_appends kill).
    mode='sigstop'   : SIGSTOP, hold ``stop_dur_s``, then SIGCONT (freeze the process
                       mid-operation — a pause window, not a crash; surfaces timeouts and
                       liveness assumptions without losing in-memory state).

    Returns the mode actually applied. Idempotent w.r.t. an already-dead child.
    """
    if proc.poll() is not None:
        return "already_dead"
    if mode == "sigkill":
        proc.send_signal(signal.SIGKILL)
        return "sigkill"
    if mode == "sigstop":
        proc.send_signal(signal.SIGSTOP)
        if stop_dur_s > 0:
            time.sleep(stop_dur_s)
        # Resume only if still alive (a concurrent kill may have won the race).
        if proc.poll() is None:
            proc.send_signal(signal.SIGCONT)
        return "sigstop_cont"
    raise ValueError(f"unknown kill mode {mode!r}")


def restart_dependency(handle: "DependencyHandle", down_dur_s: float = 0.0) -> None:
    """Stop then (after ``down_dur_s``) start a dependency the workload manages
    (Postgres / broker child process). The dependency itself is a ``DependencyHandle``
    the workload supplies — this generalizes 'restart PG during recovery' (#716) and
    'relaunch the broker'.

    The down-window is the fault: work in flight against the dependency sees a transient
    failure. A robust product retries through it; a buggy one strands.
    """
    handle.stop()
    if down_dur_s > 0:
        time.sleep(down_dur_s)
    handle.start()


class DependencyHandle:
    """Minimal contract a workload's dependency must satisfy for ``restart_dependency``.

    Workloads subclass this (e.g. a Postgres handle wrapping pg_ctl / pgserver, or a
    broker handle wrapping a subprocess). Kept abstract here so the core stays
    product-agnostic.
    """

    def stop(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def start(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def is_up(self) -> bool:  # pragma: no cover - interface
        raise NotImplementedError


class hold_lock:
    """Context manager: hold a row/table lock for ``dur_s`` via a *second* connection,
    so the workload's primary path contends with a held lock during its critical window.

    ``conn_factory`` returns a fresh DB connection (product-agnostic — the workload wires
    it). ``lock_sql`` acquires the lock (e.g. ``SELECT ... FOR UPDATE`` or ``LOCK TABLE``).
    The lock is taken on __enter__, released (connection closed / rolled back) on __exit__
    or after ``dur_s`` elapses, whichever first.

        with hold_lock(conn_factory, "LOCK TABLE t IN ACCESS EXCLUSIVE MODE", dur_s=2.0):
            ... run the contended operation ...
    """

    def __init__(self, conn_factory: Callable[[], Any], lock_sql: str, dur_s: float = 1.0):
        self._factory = conn_factory
        self._lock_sql = lock_sql
        self._dur_s = dur_s
        self._conn = None
        self._timer: Optional[threading.Timer] = None

    def __enter__(self) -> "hold_lock":
        self._conn = self._factory()
        cur = self._conn.cursor()
        cur.execute("BEGIN")
        cur.execute(self._lock_sql)
        # Auto-release after dur_s even if the body runs long.
        self._timer = threading.Timer(self._dur_s, self._release)
        self._timer.daemon = True
        self._timer.start()
        return self

    def _release(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

    def __exit__(self, *exc) -> None:
        if self._timer is not None:
            self._timer.cancel()
        self._release()


# ---------------------------------------------------------------------------
# Convenience: pre-built spaces for the common patterns
# ---------------------------------------------------------------------------


def op_index(axis: str, lo: int, hi: int) -> OpIndexSpace:
    return OpIndexSpace(axis=axis, lo=lo, hi=hi)


def latency_window(axis: str, window_ms: float, floor_ms: float = 0.0) -> LatencyWindowSpace:
    return LatencyWindowSpace(axis=axis, window_ms=window_ms, floor_ms=floor_ms)


def phase_straddle(axis: str, settle_ms: float = 0.0) -> PhaseStraddleSpace:
    return PhaseStraddleSpace(axis=axis, settle_ms=settle_ms)


def kill_restart_kill(axis: str, leg: Space, repeat_lo: int = 1, repeat_hi: int = 3) -> ScheduleSpace:
    """kill-during-recovery style schedule: repeat a sub-clock ``repeat`` times, the
    repeat count itself swept by the seed (depth varies how many recovery interrupts)."""
    return ScheduleSpace(axis=axis, legs=(leg,), repeat_lo=repeat_lo, repeat_hi=repeat_hi)


__all__ = [
    "offsets", "substream", "derive_seed",
    "OpIndexSpace", "LatencyWindowSpace", "PhaseStraddleSpace", "ScheduleSpace",
    "op_index", "latency_window", "phase_straddle", "kill_restart_kill",
    "PHASES",
    "clock_armed", "invariant", "red", "void", "green", "log", "selftest_active",
    "kill_self_child", "restart_dependency", "DependencyHandle", "hold_lock",
]
