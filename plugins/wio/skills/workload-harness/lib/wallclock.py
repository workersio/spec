#!/usr/bin/env python3
"""Wall-clock oracle — declared latency bounds are honoured.

Ships with the wio workload-harness skill; copy into the repo's .workers/lib/.

The universal claim: **an operation the product's contract bounds at ``max_s``
seconds completes within it.** A step that blows its declared budget is an
availability finding (a hang, a livelock, a missing timeout), independent of
whether it eventually returned the right answer.

Usage wraps each timed step::

    clock = WallClock()
    with clock.bound("commit", max_s=2.0):
        sut.commit()

Elapsed is measured with ``time.monotonic`` (immune to wall-clock steps). For
deterministic tests, the clock source is injectable via ``__init__(clock=...)`` —
pass a fake counter and the measurement is reproducible without real sleeping.
The measurement is recorded in a ``finally`` block, so a step that raises still
contributes its elapsed time before the exception propagates (this oracle times;
it does not swallow — the error-contract oracle owns exception grading).

Contract emitted (parsed by the wio runtime / sweep triage), via ``check_clock``:
  * ``INVARIANT wall_clock wall-clock PASS|FAIL <n> <detail|->``
  * ``ORACLE_SELFTEST PLANTED wall-clock <label> elapsed=<e>s>bound=<b>s`` —
    ``redproof_corrupt`` inflates one recorded elapsed past its bound IN THE
    RECORDED-OBSERVATION CHANNEL ONLY (never the SUT), so a green clock flips RED.

Anti-vacuity: a clock that timed no steps is ``vacuous``; ``check_clock`` returns
VOID (a green over zero measurements proves nothing).
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable


def log(msg: str) -> None:
    print(msg, flush=True)


@dataclass
class Violation:
    """One breached latency bound."""

    label: str
    code: str      # latency_exceeded
    detail: str


@dataclass
class _Measure:
    label: str
    elapsed: float
    max_s: float


class WallClock:
    """Times bounded steps and grades each against its declared budget.

    ``clock`` is the time source (default ``time.monotonic``); tests inject a
    deterministic counter so measurements are reproducible.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._measurements: list[_Measure] = []

    @contextmanager
    def bound(self, label: str, max_s: float):
        """Time the wrapped step; record its elapsed against ``max_s``."""
        start = self._clock()
        try:
            yield
        finally:
            elapsed = self._clock() - start
            self._measurements.append(_Measure(label, elapsed, max_s))

    def check(self) -> list["Violation"]:
        vios: list[Violation] = []
        for m in self._measurements:
            if m.elapsed > m.max_s:
                vios.append(Violation(
                    m.label, "latency_exceeded",
                    f"{m.label} took {m.elapsed:.4g}s > bound {m.max_s:.4g}s"))
        return vios

    def redproof_corrupt(self, rng) -> None:
        """Inflate one recorded elapsed past its bound.

        Observation channel only — mutates the recorded ``_Measure``, never the
        SUT. Prefers a within-bound measurement so a passing clock must flip RED.
        ``rng`` (a ``random.Random``) picks the target for determinism.
        """
        if not self._measurements:
            return  # vacuous — the VOID floor handles it
        within = [m for m in self._measurements if m.elapsed <= m.max_s]
        pool = within or self._measurements
        target = pool[rng.randrange(len(pool))]
        target.elapsed = target.max_s + max(1.0, abs(target.max_s))
        log(f"ORACLE_SELFTEST PLANTED wall-clock {target.label} "
            f"elapsed={target.elapsed:.4g}s>bound={target.max_s:.4g}s")

    @property
    def vacuous(self) -> bool:
        return not self._measurements


def check_clock(clock, emit=print) -> str:
    """Emit the INVARIANT line; return the verdict.

    ``INVARIANT wall_clock wall-clock PASS|FAIL <n> <detail|->``
    Returns VOID if no steps were timed, else RED on any breach, else GREEN.
    """
    vios = clock.check()
    n = len(vios)
    detail = vios[0].detail if vios else "-"
    status = "FAIL" if n else "PASS"
    emit(f"INVARIANT wall_clock wall-clock {status} {n} {detail}")
    if clock.vacuous:
        return "VOID"
    return "RED" if n else "GREEN"


__all__ = ["WallClock", "Violation", "check_clock", "log"]
